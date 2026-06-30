(() => {
    'use strict';

    const STUN = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] };
    const POLL_MS = 700;

    const $ = (id) => document.getElementById(id);

    let role = null;
    let roomCode = null;
    let guestId = null;
    let playerName = null;
    let pollTimer = null;
    let peers = {};
    let myPlayerId = null;

    let game = null;
    let names = [];
    let charById = {};
    let allCharacters = [];
    let similarAttrs = {};
    let roomConfig = null;
    let previewTimer = null;
    let currentScreen = 'menu';
    let chatMessages = [];
    let chatExpanded = true;
    let chatUnread = 0;
    let chatReady = false;

    const MIN_YEAR = window.MP_MIN_YEAR || 2010;
    const MAX_YEAR = window.MP_MAX_YEAR || 2025;

    function parseNumericAge(v) {
        if (v == null) return null;
        const s = String(v).trim();
        if (s === '???' || s === '未知' || s === '' || s === '?') return null;
        const m = s.match(/(\d{1,3})/);
        return m ? parseInt(m[1], 10) : null;
    }

    function resolveGuess(guessId, guessName) {
        if (guessId && charById[guessId]) return charById[guessId];
        if (!guessName) return null;
        const matches = Object.values(charById).filter((c) => c.名前 === guessName);
        return matches.length === 1 ? matches[0] : null;
    }

    function compareResult(guessChar, answerChar) {
        const closeness = {};
        for (const [key, answerValue] of Object.entries(answerChar)) {
            if (key === '名前' || key === 'id' || key === 'image' || key === 'has_image' || key === 'has_age') continue;
            const guessValue = guessChar[key];
            if (guessValue == null || answerValue == null) continue;
            const rule = similarAttrs[key];

            if (rule === 'numeric') {
                if (String(guessValue) === String(answerValue)) continue;
                const gn = parseNumericAge(guessValue);
                const an = parseNumericAge(answerValue);
                if (gn == null || an == null) continue;
                const diff = gn - an;
                closeness[key] = Math.abs(diff) <= 5 ? 'close' : 'far';
                closeness[key + '_arrow'] = diff < 0 ? '↑' : '↓';
            } else if (rule && typeof rule === 'object') {
                if (Array.isArray(guessValue) && Array.isArray(answerValue)) {
                    const closeList = [];
                    for (const g of guessValue) {
                        if (answerValue.includes(g)) continue;
                        for (const a of answerValue) {
                            if ((rule[a] || []).includes(g) || (rule[g] || []).includes(a)) {
                                closeList.push(g);
                                break;
                            }
                        }
                    }
                    if (closeList.length) closeness[key] = closeList;
                } else if (guessValue !== answerValue) {
                    if ((rule[answerValue] || []).includes(guessValue) || (rule[guessValue] || []).includes(answerValue)) {
                        closeness[key] = ['close'];
                    }
                }
            }
        }
        return closeness;
    }

    function collectHostConfig() {
        return {
            minYear: parseInt($('cfgMinYear')?.value, 10) || MIN_YEAR,
            maxYear: parseInt($('cfgMaxYear')?.value, 10) || MAX_YEAR,
            onlyMain: !!$('cfgOnlyMain')?.checked,
            qualityPool: $('cfgQualityPool')?.checked !== false,
        };
    }

    function filterFromConfig(chars, config) {
        if (!config) return chars;
        let minY = Math.max(MIN_YEAR, parseInt(config.minYear, 10) || MIN_YEAR);
        let maxY = Math.min(MAX_YEAR, parseInt(config.maxYear, 10) || MAX_YEAR);
        if (minY > maxY) [minY, maxY] = [maxY, minY];
        return chars.filter((c) => {
            const year = parseInt(c['初声出演の年'], 10);
            if (Number.isNaN(year) || year < minY || year > maxY) return false;
            if (config.onlyMain && c['メインキャラかどうか'] !== '是') return false;
            if (config.qualityPool && !(c.has_image && c.has_age)) return false;
            return true;
        });
    }

    function configTagsHtml(config) {
        if (!config?.labels?.length) return '';
        return config.labels.map((l) => `<span class="mp-config-tag">${l}</span>`).join('');
    }

    function applyRoomConfig(config) {
        if (!config) return;
        roomConfig = config;
        const pairs = [
            ['mpRoomConfigTags', 'mpRoomConfigBox'],
            ['mpGuestConfigTags', 'mpGuestConfigBox'],
        ];
        for (const [tagsId, boxId] of pairs) {
            const tags = $(tagsId);
            const box = $(boxId);
            if (!tags || !box) continue;
            tags.innerHTML = configTagsHtml(config);
            box.style.display = config.labels?.length ? 'block' : 'none';
        }
    }

    async function refreshConfigPreview() {
        const el = $('cfgPoolPreview');
        if (!el) return;
        try {
            const info = await api('/api/mp/preview', {
                method: 'POST',
                body: JSON.stringify({ config: collectHostConfig() }),
            });
            if (!info.poolCount) {
                el.innerHTML = '<span style="color:var(--error,#c00)">条件に合うキャラがいません</span>';
            } else {
                el.innerHTML = `候補：<strong>${info.poolCount}</strong> キャラ`;
            }
        } catch (e) {
            el.textContent = e.message;
        }
    }

    function scheduleConfigPreview() {
        clearTimeout(previewTimer);
        previewTimer = setTimeout(refreshConfigPreview, 280);
    }

    function initHostConfigForm() {
        if ($('cfgMinYear')) $('cfgMinYear').value = MIN_YEAR;
        if ($('cfgMaxYear')) $('cfgMaxYear').value = MAX_YEAR;
        if ($('cfgOnlyMain')) $('cfgOnlyMain').checked = false;
        if ($('cfgQualityPool')) $('cfgQualityPool').checked = true;
        scheduleConfigPreview();
    }

    function showScreen(name) {
        currentScreen = name;
        document.querySelectorAll('.mp-screen').forEach((el) => {
            el.style.display = el.dataset.screen === name ? 'block' : 'none';
        });
        refreshChatVisibility();
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function getMyChatName() {
        if (role === 'host') {
            return ($('hostName')?.value || game?.players?.host?.name || 'ホスト').trim().slice(0, 20) || 'ホスト';
        }
        return (playerName || $('guestNameInput')?.value || 'プレイヤー').trim().slice(0, 20) || 'プレイヤー';
    }

    function getMyChatId() {
        return role === 'host' ? 'host' : (myPlayerId || guestId || 'guest');
    }

    function isChatConnected() {
        if (role === 'host') {
            return Object.values(peers).some((p) => p.dc?.readyState === 'open');
        }
        return guestDc?.readyState === 'open';
    }

    function refreshChatVisibility() {
        const panel = $('mpChatPanel');
        if (!panel) return;
        const allowed = ['host', 'guest-wait', 'game'];
        const visible = chatReady && isChatConnected() && allowed.includes(currentScreen);
        panel.classList.toggle('open', visible);
        panel.setAttribute('aria-hidden', visible ? 'false' : 'true');
        document.body.classList.toggle('mp-chat-active', visible);
        if (visible && chatExpanded) {
            chatUnread = 0;
            updateChatBadge();
        }
    }

    function updateChatBadge() {
        const badge = $('mpChatBadge');
        if (!badge) return;
        if (chatUnread > 0 && !chatExpanded) {
            badge.textContent = chatUnread > 99 ? '99+' : String(chatUnread);
            badge.classList.add('show');
        } else {
            badge.textContent = '';
            badge.classList.remove('show');
        }
    }

    function appendChatMessage(entry) {
        chatMessages.push(entry);
        if (chatMessages.length > 200) chatMessages = chatMessages.slice(-200);
        renderChatMessages();
        const panelOpen = $('mpChatPanel')?.classList.contains('open');
        if (!entry.mine && (!chatExpanded || !panelOpen)) {
            chatUnread += 1;
            updateChatBadge();
        }
    }

    function addSystemChat(text) {
        appendChatMessage({ system: true, text, ts: Date.now() });
    }

    function renderChatMessages() {
        const box = $('mpChatMessages');
        if (!box) return;
        box.innerHTML = chatMessages.map((m) => {
            if (m.system) {
                return `<div class="mp-chat-msg system">${escapeHtml(m.text)}</div>`;
            }
            const cls = m.mine ? 'mine' : 'theirs';
            const fromLine = m.mine ? '' : `<div class="mp-chat-from">${escapeHtml(m.from)}</div>`;
            return `<div class="mp-chat-msg ${cls}">${fromLine}${escapeHtml(m.text)}</div>`;
        }).join('');
        box.scrollTop = box.scrollHeight;
    }

    function receiveChatMessage(msg, forceMine = false) {
        const text = String(msg.text || '').trim().slice(0, 300);
        if (!text) return;
        appendChatMessage({
            from: msg.from || 'プレイヤー',
            fromId: msg.fromId,
            text,
            mine: forceMine || msg.fromId === getMyChatId(),
            ts: msg.ts || Date.now(),
        });
    }

    function sendChatMessage(text) {
        if (!isChatConnected()) return;
        text = String(text || '').trim().slice(0, 300);
        if (!text) return;
        const payload = {
            type: 'chat',
            from: getMyChatName(),
            fromId: getMyChatId(),
            text,
            ts: Date.now(),
        };
        receiveChatMessage(payload, true);
        if (role === 'host') {
            broadcast(payload);
        } else {
            guestSend(payload);
        }
        const input = $('mpChatInput');
        if (input) input.value = '';
    }

    function setChatReady(ready) {
        chatReady = ready;
        refreshChatVisibility();
    }

    function resetChat() {
        chatMessages = [];
        chatUnread = 0;
        chatReady = false;
        chatExpanded = true;
        const panel = $('mpChatPanel');
        if (panel) {
            panel.classList.remove('open', 'collapsed');
            panel.setAttribute('aria-hidden', 'true');
        }
        document.body.classList.remove('mp-chat-active');
        const toggle = $('mpChatToggle');
        if (toggle) toggle.textContent = '−';
        renderChatMessages();
        updateChatBadge();
    }

    function bindChatUI() {
        $('mpChatSend')?.addEventListener('click', () => sendChatMessage($('mpChatInput')?.value));
        $('mpChatInput')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.isComposing) {
                e.preventDefault();
                sendChatMessage($('mpChatInput')?.value);
            }
        });
        const toggleChat = () => {
            chatExpanded = !chatExpanded;
            const panel = $('mpChatPanel');
            const btn = $('mpChatToggle');
            if (panel) panel.classList.toggle('collapsed', !chatExpanded);
            if (btn) btn.textContent = chatExpanded ? '−' : '+';
            if (chatExpanded) {
                chatUnread = 0;
                updateChatBadge();
                const box = $('mpChatMessages');
                if (box) box.scrollTop = box.scrollHeight;
            }
        };
        $('mpChatHeader')?.addEventListener('click', (e) => {
            if (e.target.closest('#mpChatSend, #mpChatInput, #mpChatToggle')) return;
            toggleChat();
        });
        $('mpChatToggle')?.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleChat();
        });
    }

    function setStatus(text, type = '') {
        const el = $('mpStatus');
        if (!el) return;
        el.textContent = text;
        el.className = 'mp-status' + (type ? ` mp-status-${type}` : '');
        el.style.display = text ? 'block' : 'none';
    }

    async function api(path, opts = {}) {
        const res = await fetch(path, {
            headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
            ...opts,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'リクエスト失敗');
        return data;
    }

    function stopPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
    }

    function startPolling(fn) {
        stopPolling();
        pollTimer = setInterval(fn, POLL_MS);
        fn();
    }

    // --- Signaling ---

    async function postSignal(targetGuestId, type, payload, signalRole = role) {
        await api(`/api/mp/room/${roomCode}/signal`, {
            method: 'POST',
            body: JSON.stringify({
                role: signalRole,
                guest_id: targetGuestId,
                type,
                payload,
            }),
        });
    }

    // --- WebRTC Host ---

    function sendTo(playerId, msg) {
        const peer = peers[playerId];
        if (peer?.dc?.readyState === 'open') {
            peer.dc.send(JSON.stringify(msg));
            return true;
        }
        return false;
    }

    function broadcast(msg, excludeId = null) {
        if (role !== 'host') return;
        const raw = JSON.stringify(msg);
        for (const [pid, peer] of Object.entries(peers)) {
            if (pid === excludeId) continue;
            if (peer.dc?.readyState === 'open') peer.dc.send(raw);
        }
    }

    function broadcastGameStart() {
        const pool = Object.values(charById);
        const startMsg = {
            type: 'game_start',
            names,
            characters: pool,
            config: roomConfig,
            players: Object.values(game.players).map((p) => ({ id: p.id, name: p.name, attempts: 0, status: 'playing' })),
        };
        broadcast(startMsg);
        for (const pid of Object.keys(game.players)) {
            if (pid !== 'host') syncPlayer(pid);
        }
    }

    async function hostConnectGuest(gid, playerName = 'プレイヤー') {
        if (peers[gid]?.pc) return;

        const pc = new RTCPeerConnection(STUN);
        const dc = pc.createDataChannel('game');
        peers[gid] = { pc, dc, playerName };

        setupDataChannel(gid, dc, true);

        pc.onicecandidate = (e) => {
            if (e.candidate) postSignal(gid, 'ice', e.candidate).catch(() => {});
        };

        pc.onconnectionstatechange = () => {
            if (pc.connectionState === 'failed') {
                setStatus(`接続失敗: ${playerName}`, 'error');
            }
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await postSignal(gid, 'sdp_offer', offer);
    }

    async function hostHandleSignal(event) {
        const gid = event.guest_id;
        if (!gid || !peers[gid]?.pc) return;
        const peer = peers[gid];
        const { type, payload } = event;

        if (type === 'sdp_answer') {
            await peer.pc.setRemoteDescription(new RTCSessionDescription(payload));
            if (peer.iceQueue) {
                for (const c of peer.iceQueue) {
                    try { await peer.pc.addIceCandidate(new RTCIceCandidate(c)); } catch (_) {}
                }
                peer.iceQueue = [];
            }
        } else if (type === 'ice') {
            if (peer.pc.remoteDescription) {
                try { await peer.pc.addIceCandidate(new RTCIceCandidate(payload)); } catch (_) {}
            } else {
                peer.iceQueue = peer.iceQueue || [];
                peer.iceQueue.push(payload);
            }
        }
    }

    // --- WebRTC Guest ---

    let guestPc = null;
    let guestDc = null;
    let guestIceQueue = [];

    async function guestHandleSignal(sig) {
        const { type, payload } = sig;

        if (type === 'sdp_offer') {
            guestPc = new RTCPeerConnection(STUN);
            guestIceQueue = [];
            guestPc.ondatachannel = (e) => {
                guestDc = e.channel;
                setupDataChannel(guestId, guestDc, false);
            };
            guestPc.onicecandidate = (e) => {
                if (e.candidate) postSignal(guestId, 'ice', e.candidate, 'guest').catch(() => {});
            };
            await guestPc.setRemoteDescription(new RTCSessionDescription(payload));
            for (const c of guestIceQueue) {
                await guestPc.addIceCandidate(new RTCIceCandidate(c));
            }
            guestIceQueue = [];
            const answer = await guestPc.createAnswer();
            await guestPc.setLocalDescription(answer);
            await postSignal(guestId, 'sdp_answer', answer, 'guest');
        } else if (type === 'ice') {
            if (guestPc?.remoteDescription) {
                try { await guestPc.addIceCandidate(new RTCIceCandidate(payload)); } catch (_) {}
            } else {
                guestIceQueue.push(payload);
            }
        }
    }

    function setupDataChannel(pid, dc, isHostSide) {
        dc.onopen = () => {
            setChatReady(true);
            refreshChatVisibility();
            if (role === 'host') {
                sendTo(pid, { type: 'welcome', playerId: pid });
                if (!chatMessages.some((m) => m.system && m.text.includes('接続'))) {
                    addSystemChat('接続しました。チャットが使えます。');
                }
                if (game?.started) {
                    const pool = Object.values(charById);
                    sendTo(pid, {
                        type: 'game_start',
                        names,
                        characters: pool,
                        config: roomConfig,
                        players: Object.values(game.players).map((p) => ({
                            id: p.id, name: p.name, attempts: p.attempts, status: p.status,
                        })),
                    });
                    syncPlayer(pid);
                }
            } else if (role === 'guest') {
                setStatus('接続完了！ホストの開始を待っています…', 'ok');
                addSystemChat('接続しました。チャットが使えます。');
            }
        };

        dc.onmessage = (e) => {
            let msg;
            try { msg = JSON.parse(e.data); } catch { return; }

            if (role === 'host') {
                handleHostMessage(pid, msg);
            } else {
                handleGuestMessage(msg);
            }
        };
    }

    // --- Game Host Logic ---

    function initHostGame() {
        const hostName = ($('hostName')?.value || 'ホスト').trim().slice(0, 20) || 'ホスト';
        const pool = filterFromConfig(window.MP_ALL_CHARACTERS || [], roomConfig);
        if (!pool.length) {
            setStatus('条件に合うキャラがいません。設定を変更してください。', 'error');
            return;
        }
        const answerChar = pool[Math.floor(Math.random() * pool.length)];

        game = {
            started: true,
            ended: false,
            winner: null,
            answer: answerChar,
            players: {
                host: {
                    id: 'host',
                    name: hostName,
                    attempts: 0,
                    guessed: [],
                    closeness: {},
                    status: 'playing',
                    error: null,
                    result: null,
                },
            },
        };

        for (const [gid, peer] of Object.entries(peers)) {
            if (!peer.pc) continue;
            game.players[gid] = {
                id: gid,
                name: peer.playerName || 'プレイヤー',
                attempts: 0,
                guessed: [],
                closeness: {},
                status: 'playing',
                error: null,
                result: null,
            };
        }

        names = pool.map((c) => c.名前);
        charById = Object.fromEntries(pool.map((c) => [c.id, c]));
        allCharacters = window.MP_ALL_CHARACTERS || [];

        broadcastGameStart();
        // データチャネルがまだ開いていない場合に再送
        setTimeout(() => { if (game?.started && !game.ended) broadcastGameStart(); }, 1500);

        syncAll();
        showScreen('game');
        renderGame();
        setStatus('ゲーム進行中 — 先に正解した方が勝ち！', 'ok');
        $('mpStartBtn').disabled = true;
    }

    function handleHostMessage(pid, msg) {
        if (msg.type === 'chat') {
            const payload = {
                type: 'chat',
                from: msg.from || peers[pid]?.playerName || 'プレイヤー',
                fromId: msg.fromId || pid,
                text: msg.text,
                ts: msg.ts || Date.now(),
            };
            receiveChatMessage(payload, false);
            broadcast(payload, pid);
            return;
        }

        if (!game?.started || game.ended) return;
        const player = game.players[pid];
        if (!player || player.status !== 'playing') return;

        if (msg.type === 'guess') {
            processGuess(pid, msg.guess_id || '', (msg.guess_name || '').trim());
        }
    }

    function processGuess(pid, guessId, guessName) {
        const player = game.players[pid];
        player.error = null;

        const guessedChar = resolveGuess(guessId, guessName);
        if (!guessName && !guessId) {
            player.error = 'キャラ名を入力してください。';
            syncPlayer(pid);
            return;
        }
        if (!guessedChar) {
            player.error = 'そのキャラクターは見つかりませんでした。';
            syncPlayer(pid);
            return;
        }
        if (player.guessed.includes(guessedChar.id)) {
            player.error = `${guessedChar.名前} はすでに推測されています。`;
            syncPlayer(pid);
            return;
        }

        player.attempts += 1;
        player.guessed.push(guessedChar.id);

        if (guessedChar.id === game.answer.id) {
            player.status = 'won';
            player.result = `✅ 正解！ ${guessedChar.名前}`;
            if (!game.winner) {
                game.winner = { id: pid, name: player.name };
                game.ended = true;
                endGameForAll();
            }
        } else {
            player.closeness[guessedChar.id] = compareResult(guessedChar, game.answer);
        }
        syncAll();
        if (role === 'host') renderGame();
    }

    function endGameForAll() {
        const reveal = {
            type: 'game_end',
            winner: game.winner,
            answer: game.answer,
        };
        broadcast(reveal);
        for (const p of Object.values(game.players)) {
            if (p.status === 'playing') {
                p.status = 'lost';
                p.result = `終了 — 正解は ${game.answer.名前}`;
            }
        }
        syncAll();
        if (role === 'host') renderGame();
    }

    function buildPlayerState(pid) {
        const player = game.players[pid];
        const publicPlayers = Object.values(game.players).map((p) => ({
            id: p.id,
            name: p.name,
            attempts: p.attempts,
            status: p.status,
        }));
        return {
            type: 'state_update',
            you: {
                attempts: player.attempts,
                guessed: player.guessed,
                closeness: player.closeness,
                status: player.status,
                error: player.error,
                result: player.result,
            },
            players: publicPlayers,
            winner: game.winner,
        };
    }

    function syncPlayer(pid) {
        if (pid === 'host') {
            renderGame();
            return;
        }
        sendTo(pid, buildPlayerState(pid));
    }

    function syncAll() {
        if (role === 'host') {
            renderGame();
            for (const pid of Object.keys(game.players)) {
                if (pid !== 'host') syncPlayer(pid);
            }
        }
    }

    // --- Game Guest Logic ---

    let guestState = null;

    function handleGuestMessage(msg) {
        if (msg.type === 'welcome') {
            myPlayerId = msg.playerId;
        } else if (msg.type === 'chat') {
            receiveChatMessage(msg, false);
        } else if (msg.type === 'game_start') {
            names = msg.names;
            charById = Object.fromEntries(msg.characters.map((c) => [c.id, c]));
            allCharacters = window.MP_ALL_CHARACTERS || msg.characters;
            if (msg.config) applyRoomConfig(msg.config);
            guestState = {
                attempts: 0, guessed: [], closeness: {}, status: 'playing',
                error: null, result: null,
            };
            game = { started: true, ended: false, players: msg.players, winner: null };
            showScreen('game');
            setStatus('対戦開始！先に正解した方が勝ち！', 'ok');
            renderGame();
        } else if (msg.type === 'state_update') {
            guestState = msg.you;
            game = game || { started: true };
            game.players = msg.players;
            game.winner = msg.winner;
            renderGame();
        } else if (msg.type === 'game_end') {
            game = game || { started: true };
            game.winner = msg.winner;
            game.answer = msg.answer;
            game.ended = true;
            if (guestState) {
                if (guestState.status !== 'won') guestState.status = 'lost';
                if (!guestState.result) {
                    guestState.result = game.winner?.id === myPlayerId
                        ? `✅ 正解！`
                        : `❌ ${game.winner?.name || '相手'}が先に正解…`;
                }
            }
            showScreen('game');
            renderGame();
        }
    }

    function guestSend(msg) {
        if (guestDc?.readyState === 'open') guestDc.send(JSON.stringify(msg));
    }

    // --- UI Render ---

    const ATTRS = [
        ['初登場の作品', false], ['初登場の年齢', false], ['性別', true],
        ['種族', true], ['出身', true], ['髪色', true], ['肩書', true],
        ['初声出演の年', false], ['作品ジャンル', true], ['出演メディア', true],
    ];

    function tagHtml(text, cls) {
        return `<span class="info-tag el-tag--${cls}">${text}</span>`;
    }

    function renderAttrTags(char, closenessForChar, answerChar) {
        return ATTRS.map(([label, isList]) => {
            const value = char[label];
            let tags = '';
            if (isList) {
                tags = value.map((item) => {
                    const av = answerChar[label];
                    if (char.id === answerChar.id) return tagHtml(item, 'success');
                    if (av.includes(item)) return tagHtml(item, 'success');
                    if (closenessForChar?.[label]?.includes(item)) return tagHtml(item, 'warning');
                    return tagHtml(item, 'info');
                }).join('');
            } else {
                const av = answerChar[label];
                if (char.id === answerChar.id || value === av) {
                    tags = tagHtml(value, 'success');
                } else if (closenessForChar?.[label] === 'close') {
                    tags = tagHtml(value + (closenessForChar[label + '_arrow'] || ''), 'warning');
                } else if (closenessForChar?.[label] === 'far') {
                    tags = tagHtml(value + (closenessForChar[label + '_arrow'] || ''), 'info');
                } else {
                    tags = tagHtml(value, 'info');
                }
            }
            return `<div class="attr-block"><div class="info-label">${label}</div><div class="tag-group">${tags}</div></div>`;
        }).join('');
    }

    function renderCard(char, closenessMap, answerChar) {
        const shortName = char.名前.split('（')[0];
        return `<div class="horizontal-card">
            <div class="card-portrait">
                <div class="card-name">${shortName}</div>
                <div class="card-img-box"><img src="${char.image || '/static/char_placeholder.png'}" class="card-img" alt="" onerror="this.onerror=null;this.src='/static/char_placeholder.png';"></div>
            </div>
            <div class="card-attrs">${renderAttrTags(char, closenessMap, answerChar)}</div>
        </div>`;
    }

    function renderGame() {
        const area = $('mpGameArea');
        if (!area) return;

        let state, answerChar, playerList;

        if (role === 'host' && game?.started) {
            const me = game.players.host;
            state = me;
            answerChar = game.answer;
            playerList = game.players;
            myPlayerId = 'host';
        } else if (guestState) {
            state = guestState;
            answerChar = game?.answer || { 名前: '???' };
            playerList = null;
        } else return;

        const canPlay = state.status === 'playing' && !game?.ended;
        const myId = role === 'host' ? 'host' : myPlayerId;
        const plist = playerList
            ? Object.values(playerList)
            : (game?.players || []);

        const playersHtml = `<div class="mp-scoreboard">
            <div class="mp-scoreboard-title">対戦状況 <span class="mp-scoreboard-hint">（推測回数はお互いに見えます）</span></div>
            <div class="mp-players">${plist.map((p) => {
                const isMe = p.id === myId;
                const badge = p.status === 'won' ? '🏆' : p.status === 'lost' ? '💤' : '🎮';
                const label = isMe ? 'あなた' : '相手';
                const cls = isMe ? 'mp-player-chip mp-player-self' : 'mp-player-chip mp-player-rival';
                return `<span class="${cls}">${badge} ${label} · ${p.name}：<strong>${p.attempts}</strong> 回</span>`;
            }).join('')}</div>
        </div>`;

        let cardsHtml = '';
        const ans = role === 'host' ? game.answer : (game?.answer || null);
        const showAnswer = state.status !== 'playing' && ans;
        if (showAnswer) {
            cardsHtml += `<h3 class="section-title">正解</h3><div class="card-list-vertical">${renderCard(ans, {}, ans)}</div>`;
        }
        if (state.guessed.length) {
            cardsHtml += `<h3 class="section-title">あなたの推測</h3><div class="card-list-vertical">`;
            for (const gid of state.guessed) {
                const ch = charById[gid];
                if (!ch) continue;
                const ref = ans || ch;
                cardsHtml += renderCard(ch, state.closeness[gid] || {}, ref);
            }
            cardsHtml += '</div>';
        }

        const configHtml = roomConfig?.labels?.length
            ? `<div class="mp-config-box" style="margin-top:0;margin-bottom:12px">
                <div class="mp-config-title">本局のルール</div>
                <div class="mp-config-tags">${configTagsHtml(roomConfig)}</div>
               </div>`
            : '';

        area.innerHTML = `
            ${configHtml}
            ${playersHtml}
            <div class="mp-my-attempts">あなたの推測：<strong>${state.attempts}</strong> 回</div>
            ${state.error ? `<div class="message message-error">${state.error}</div>` : ''}
            ${state.result ? `<div class="message message-result">${state.result}</div>` : ''}
            ${game?.winner ? `<div class="message message-result">🏆 勝者：${game.winner.name}</div>` : ''}
            <section class="game-panel" style="margin-top:16px">
                <div class="search-wrap">
                    <input id="mpGuessInput" placeholder="キャラ名を入力…" ${canPlay ? '' : 'disabled'}>
                    <ul id="mpSuggestions" class="suggestions"></ul>
                </div>
                <div class="button-row">
                    <button class="btn btn-primary" id="mpSubmitBtn" ${canPlay ? '' : 'disabled'}>送信</button>
                </div>
            </section>
            ${cardsHtml}
        `;

        if (canPlay) bindGuessUI();
    }

    function bindGuessUI() {
        const input = $('mpGuessInput');
        const suggestions = $('mpSuggestions');
        const submitBtn = $('mpSubmitBtn');
        if (!input) return;

        const guessed = role === 'host'
            ? game.players.host.guessed
            : (guestState?.guessed || []);

        let pendingGuessId = '';

        function updateSuggestions() {
            const q = input.value.trim();
            suggestions.innerHTML = '';
            if (!q) { suggestions.style.display = 'none'; return; }
            const roomParam = roomCode ? `&room=${encodeURIComponent(roomCode)}` : '';
            fetch(`/api/search?q=${encodeURIComponent(q)}&exclude=${guessed.join(',')}${roomParam}`)
                .then((r) => r.json())
                .then((matches) => {
                    suggestions.innerHTML = '';
                    if (!matches.length) { suggestions.style.display = 'none'; return; }
                    matches.forEach((item) => {
                        const li = document.createElement('li');
                        li.innerHTML = `${item.name}<span class="suggest-work">${item.work}</span>`;
                        li.onclick = () => {
                            input.value = item.name;
                            pendingGuessId = item.id;
                            suggestions.style.display = 'none';
                        };
                        suggestions.appendChild(li);
                    });
                    suggestions.style.display = 'block';
                })
                .catch(() => { suggestions.style.display = 'none'; });
        }

        input.addEventListener('input', () => { pendingGuessId = ''; updateSuggestions(); });
        input.addEventListener('focus', updateSuggestions);

        function doGuess() {
            const name = input.value.trim();
            if (!name) return;
            if (role === 'host') {
                processGuess('host', pendingGuessId, name);
            } else {
                guestSend({ type: 'guess', guess_id: pendingGuessId, guess_name: name });
            }
            input.value = '';
            pendingGuessId = '';
        }

        submitBtn?.addEventListener('click', doGuess);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); doGuess(); }
        });
    }

    // --- Lobby actions ---

    async function hostCreateRoom() {
        try {
            const config = collectHostConfig();
            const hostName = ($('hostName')?.value || 'ホスト').trim().slice(0, 20) || 'ホスト';
            const data = await api('/api/mp/room', {
                method: 'POST',
                body: JSON.stringify({ config, host_name: hostName }),
            });
            role = 'host';
            roomCode = data.room_code;
            applyRoomConfig(data.config);
            $('mpRoomCode').textContent = roomCode;
            $('mpRoomCodeBox').style.display = 'block';
            $('mpHostActions').style.display = 'block';
            const linkEl = $('mpJoinLink');
            if (linkEl) linkEl.textContent = `${location.origin}/multiplayer?join=${roomCode}`;
            showScreen('host');
            setStatus('参加者を待っています…', 'wait');

            startPolling(async () => {
                try {
                    const res = await api(`/api/mp/room/${roomCode}/poll?role=host`);
                    if (res.config) applyRoomConfig(res.config);
                    renderGuestList(res.guests || []);
                    for (const ev of res.events || []) {
                        if (ev.type === 'guest_joined') {
                            if (!peers[ev.guest_id]?.pc) {
                                await hostConnectGuest(ev.guest_id, ev.player_name);
                                if (game?.started && !game.players[ev.guest_id]) {
                                    game.players[ev.guest_id] = {
                                        id: ev.guest_id,
                                        name: ev.player_name,
                                        attempts: 0, guessed: [], closeness: {},
                                        status: 'playing', error: null, result: null,
                                    };
                                    broadcastGameStart();
                                }
                            }
                        } else {
                            await hostHandleSignal(ev);
                        }
                    }
                } catch (e) {
                    setStatus(e.message, 'error');
                }
            });
        } catch (e) {
            setStatus(e.message, 'error');
        }
    }

    function renderGuestList(guests) {
        const el = $('mpGuestList');
        if (!el) return;
        if (!guests.length) {
            el.innerHTML = '<p class="mp-hint">まだ参加者がいません…</p>';
            return;
        }
        el.innerHTML = guests.map((g) =>
            `<div class="mp-guest-item">🟢 ${g.player_name}</div>`
        ).join('');
        $('mpStartBtn').disabled = false;
    }

    async function guestJoinRoom() {
        const code = ($('joinCodeInput')?.value || '').trim();
        const name = ($('guestNameInput')?.value || '').trim();
        if (!/^\d{6}$/.test(code)) {
            setStatus('6桁の部屋番号を入力してください', 'error');
            return;
        }
        try {
            const data = await api(`/api/mp/room/${code}/join`, {
                method: 'POST',
                body: JSON.stringify({ player_name: name || 'プレイヤー' }),
            });
            role = 'guest';
            roomCode = code;
            guestId = data.guest_id;
            playerName = name;
            applyRoomConfig(data.config);
            showScreen('guest-wait');
            setStatus(data.host_name ? `${data.host_name} の部屋に接続中…` : 'ホストと接続中…', 'wait');

            startPolling(async () => {
                try {
                    const res = await api(`/api/mp/room/${roomCode}/poll?role=guest&guest_id=${guestId}`);
                    if (res.config) applyRoomConfig(res.config);
                    for (const sig of res.signals || []) {
                        await guestHandleSignal(sig);
                    }
                } catch (e) {
                    setStatus(e.message, 'error');
                }
            });
        } catch (e) {
            setStatus(e.message, 'error');
        }
    }

    function init() {
        similarAttrs = window.MP_SIMILAR_ATTRS || {};
        allCharacters = window.MP_ALL_CHARACTERS || [];
        showScreen('menu');

        $('mpHostBtn')?.addEventListener('click', () => {
            initHostConfigForm();
            showScreen('host-config');
        });
        $('mpJoinBtn')?.addEventListener('click', () => showScreen('join'));
        $('mpBackBtn')?.addEventListener('click', () => { stopPolling(); resetChat(); showScreen('menu'); setStatus(''); });
        $('mpBackFromConfigBtn')?.addEventListener('click', () => { showScreen('menu'); setStatus(''); });
        $('mpCreateRoomBtn')?.addEventListener('click', hostCreateRoom);
        $('mpJoinRoomBtn')?.addEventListener('click', guestJoinRoom);
        $('mpStartBtn')?.addEventListener('click', initHostGame);
        bindChatUI();

        for (const id of ['cfgMinYear', 'cfgMaxYear', 'cfgOnlyMain', 'cfgQualityPool']) {
            const el = $(id);
            el?.addEventListener('input', scheduleConfigPreview);
            el?.addEventListener('change', scheduleConfigPreview);
        }

        const prefill = window.MP_JOIN_CODE;
        if (prefill) {
            showScreen('join');
            if ($('joinCodeInput')) $('joinCodeInput').value = prefill;
        }
    }

    document.addEventListener('DOMContentLoaded', init);
})();
