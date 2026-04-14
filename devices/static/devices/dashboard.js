document.addEventListener('DOMContentLoaded', function () {
    const main = document.querySelector('.sim-main');
    if (!main) {
        return;
    }

    const statusUrl = main.dataset.statusUrl;
    const startUrl = main.dataset.startUrl;
    const stopUrl = main.dataset.stopUrl;
    const checkGatewayUrl = main.dataset.checkGatewayUrl;
    const logsUrl = main.dataset.logsUrl;

    const modeTarget = document.getElementById('runtime-mode');
    const modeDetailTarget = document.getElementById('runtime-mode-detail');
    const summaryTarget = document.getElementById('runtime-summary');
    const pillTarget = document.getElementById('runtime-pill');
    const pidTarget = document.getElementById('active-pid');
    const logTarget = document.getElementById('log-output');
    const devicesTotalTarget = document.getElementById('devices-total');
    const devicesWithTokenTarget = document.getElementById('devices-with-token');
    const devicesWithoutTokenTarget = document.getElementById('devices-without-token');
    const gatewaysTotalTarget = document.getElementById('gateways-total');
    const gatewaysActiveTarget = document.getElementById('gateways-active');
    const gatewayNameTarget = document.getElementById('gateway-name');
    const gatewayAuthTarget = document.getElementById('gateway-auth');
    const gatewayCheckResult = document.getElementById('gateway-check-result');

    const startButton = document.getElementById('start-button');
    const stopButton = document.getElementById('stop-button');
    const checkGatewayButton = document.getElementById('check-gateway-button');
    const refreshButton = document.getElementById('refresh-logs');
    const lastUpdated = document.getElementById('last-updated');
    const randomizeToggle = document.getElementById('toggle-randomize');
    const memoryToggle = document.getElementById('toggle-memory');
    const influxToggle = document.getElementById('toggle-influx');

    function csrfToken() {
        const cookie = document.cookie.split('; ').find((row) => row.startsWith('csrftoken_iot_simulator='));
        return cookie ? cookie.split('=')[1] : '';
    }

    function renderRuntime(payload) {
        const runtime = payload.runtime;
        if (!runtime) return;
        modeTarget.textContent = runtime.mode;
        modeDetailTarget.textContent = runtime.mode;
        pillTarget.textContent = runtime.mode;
        pidTarget.textContent = runtime.active_pid || '-';
        summaryTarget.textContent = runtime.is_running ? 'Processo ativo e monitorado pela dashboard.' : 'Nenhum processo de telemetria ativo';

        // Toggle start/stop button states based on runtime
        if (startButton) startButton.disabled = !!runtime.is_running;
        if (stopButton) stopButton.disabled = !runtime.is_running;
        if (pillTarget) {
            pillTarget.classList.toggle('pill-running', !!runtime.is_running);
        }

        if (payload.stats) {
            if (devicesTotalTarget) devicesTotalTarget.textContent = payload.stats.devices_total;
            if (devicesWithTokenTarget) devicesWithTokenTarget.textContent = payload.stats.devices_with_token;
            if (devicesWithoutTokenTarget) devicesWithoutTokenTarget.textContent = payload.stats.devices_without_token;
            if (gatewaysTotalTarget) gatewaysTotalTarget.textContent = payload.stats.gateways_total;
            if (gatewaysActiveTarget) gatewaysActiveTarget.textContent = payload.stats.gateways_active;
        }

        if (payload.active_gateway) {
            if (gatewayNameTarget) gatewayNameTarget.textContent = payload.active_gateway.name;
            if (gatewayAuthTarget) gatewayAuthTarget.textContent = payload.active_gateway.auth_method;
        } else {
            if (gatewayNameTarget) gatewayNameTarget.textContent = 'Nenhum';
            if (gatewayAuthTarget) gatewayAuthTarget.textContent = '—';
        }

        if (payload.recent_logs) {
            logTarget.textContent = payload.recent_logs.length ? payload.recent_logs.join('\n') : 'Sem logs do runtime gerenciado até o momento.';
            logTarget.scrollTop = logTarget.scrollHeight;
        }
    }

    async function refreshStatus() {
        const response = await fetch(statusUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' });
        if (!response.ok) {
            return;
        }
        renderRuntime(await response.json());
    }

    async function refreshLogs() {
        if (refreshLogs._running) return; // avoid overlapping refreshes
        refreshLogs._running = true;
        refreshButton.classList.add('loading');
        try {
            const response = await fetch(logsUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' });
            if (!response.ok) {
                return;
            }
            const payload = await response.json();
            logTarget.textContent = payload.lines.length ? payload.lines.join('\n') : 'Sem logs do runtime gerenciado até o momento.';
            logTarget.scrollTop = logTarget.scrollHeight;
            if (lastUpdated) lastUpdated.textContent = new Date().toLocaleTimeString();
        } finally {
            refreshButton.classList.remove('loading');
            refreshLogs._running = false;
        }
    }

    async function postControl(url) {
        // show loading state on buttons during control operations
        try {
            if (startButton) startButton.classList.add('loading');
            if (stopButton) stopButton.classList.add('loading');

            const response = await fetch(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken(),
                },
                body: JSON.stringify({
                    randomize: randomizeToggle.checked,
                    memory: memoryToggle.checked,
                    use_influxdb: influxToggle.checked,
                }),
            });

            if (!response.ok) {
                let payload = {};
                try { payload = await response.json(); } catch (e) {}
                window.alert(payload.message || 'Falha ao executar comando.');
                return;
            }
            renderRuntime(await response.json());
            await refreshLogs();
        } finally {
            if (startButton) startButton.classList.remove('loading');
            if (stopButton) stopButton.classList.remove('loading');
        }
    }

    async function checkGateway() {
        if (!checkGatewayUrl) return;

        try {
            if (checkGatewayButton) checkGatewayButton.classList.add('loading');
            const response = await fetch(checkGatewayUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken(),
                },
                body: '{}',
            });

            let payload = {};
            try { payload = await response.json(); } catch (e) {}
            const ok = response.ok && payload.ok;
            if (gatewayCheckResult) {
                gatewayCheckResult.textContent = payload.message || (ok ? 'Gateway valido.' : 'Falha ao validar gateway.');
                gatewayCheckResult.style.color = ok ? '#166534' : '#b91c1c';
            }
        } finally {
            if (checkGatewayButton) checkGatewayButton.classList.remove('loading');
        }
    }

    startButton.addEventListener('click', function () {
        startButton.disabled = true;
        postControl(startUrl).finally(() => { /* renderRuntime will set proper state */ });
    });

    stopButton.addEventListener('click', function () {
        stopButton.disabled = true;
        postControl(stopUrl).finally(() => { /* renderRuntime will set proper state */ });
    });

    refreshButton.addEventListener('click', refreshLogs);
    if (checkGatewayButton) {
        checkGatewayButton.addEventListener('click', checkGateway);
    }

    refreshStatus();
    refreshLogs();
    window.setInterval(refreshStatus, 5000);
    // poll status frequently but only refresh logs if not already refreshing
    window.setInterval(function(){ if(!refreshLogs._running) refreshLogs(); }, 6000);
});