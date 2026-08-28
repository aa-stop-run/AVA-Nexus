/**
 * AVA Stark HUD 3.0 — Offcanvas HUD Drawer Manager
 * Manages dynamic sliding telemetry deep-dive panels,
 * contextual data population, and keyboard navigation.
 */

class HUDDrawerManager {
    constructor() {
        this.backdrop = document.getElementById('hud-drawer-backdrop');
        this.panel = document.getElementById('hud-drawer-panel');
        this.iconEl = document.getElementById('drawer-icon');
        this.titleEl = document.getElementById('drawer-title');
        this.bodyEl = document.getElementById('drawer-body');
        this.linkEl = document.getElementById('drawer-external-link');

        this.isOpen = false;
        this.initKeyListeners();
    }

    initKeyListeners() {
        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });
    }

    open(type) {
        if (!this.panel || !this.backdrop) return;

        this.populateContent(type);

        this.backdrop.classList.remove('hidden');
        setTimeout(() => {
            this.backdrop.classList.add('opacity-100');
            this.panel.classList.remove('drawer-closed');
            this.panel.classList.add('drawer-open');
        }, 10);

        this.isOpen = true;
    }

    close() {
        if (!this.panel || !this.backdrop) return;

        this.panel.classList.remove('drawer-open');
        this.panel.classList.add('drawer-closed');
        this.backdrop.classList.remove('opacity-100');

        setTimeout(() => {
            this.backdrop.classList.add('hidden');
            this.isOpen = false;
        }, 320);
    }

    populateContent(type) {
        if (!this.bodyEl || !this.titleEl || !this.iconEl || !this.linkEl) return;

        switch (type) {
            case 'wealth':
                this.iconEl.innerText = '[$]';
                this.titleEl.innerText = 'Património & Finanças // HUD';
                this.linkEl.href = 'http://localhost:8081';
                this.linkEl.querySelector('span').innerText = 'Abrir Finanças (:8081)';
                this.bodyEl.innerHTML = `
                    <div class="p-3 rounded-xl bg-slate-900/90 border border-cyan-500/30 space-y-2">
                        <span class="text-[9px] uppercase text-cyan-300 font-bold block tracking-wider">Balanço Consolidado</span>
                        <div class="flex justify-between items-center text-sm border-b border-white/10 pb-2">
                            <span class="text-slate-400">Património Líquido:</span>
                            <span class="font-bold text-white text-base font-mono">${document.querySelector('.liquid-wealth-wave')?.parentElement?.querySelector('.text-2xl')?.innerText || '€ 0,00'}</span>
                        </div>
                        <div class="space-y-1 pt-1 text-[11px]">
                            <div class="flex justify-between text-emerald-400">
                                <span>+ Total de Ativos (Imóveis/Bens):</span>
                                <span class="font-bold">Calculado em tempo real</span>
                            </div>
                            <div class="flex justify-between text-rose-400">
                                <span>- Passivo & Dívidas Bancárias:</span>
                                <span class="font-bold">Em amortização nominal</span>
                            </div>
                        </div>
                    </div>

                    <div class="p-3 rounded-xl bg-slate-900/90 border border-cyan-500/20 space-y-2">
                        <span class="text-[9px] uppercase text-slate-400 font-bold block tracking-wider">Ações de Gestão</span>
                        <div class="grid grid-cols-2 gap-2">
                            <a href="http://localhost:8081" target="_blank" class="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 hover:bg-cyan-500/20 text-cyan-300 text-center font-bold text-[10px]">
                                + Nova Despesa
                            </a>
                            <a href="http://localhost:8081" target="_blank" class="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 hover:bg-emerald-500/20 text-emerald-300 text-center font-bold text-[10px]">
                                Extrato de Contas
                            </a>
                        </div>
                    </div>
                `;
                break;

            case 'health':
                this.iconEl.innerText = '[♥]';
                this.titleEl.innerText = 'Saúde Familiar & Clínica // HUD';
                this.linkEl.href = 'http://localhost:8083';
                this.linkEl.querySelector('span').innerText = 'Abrir Saúde (:8083)';
                this.bodyEl.innerHTML = `
                    <div class="p-3 rounded-xl bg-rose-950/30 border border-rose-500/30 space-y-2">
                        <span class="text-[9px] uppercase text-rose-300 font-bold block tracking-wider">Perfis Clínicos Ativos</span>
                        <div class="space-y-1.5 pt-1">
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <span class="font-bold text-white">aa-stop-run</span>
                                <span class="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-bold">NOMINAL // 100%</span>
                            </div>
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <span class="font-bold text-white">Member</span>
                                <span class="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-bold">NOMINAL // 100%</span>
                            </div>
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <span class="font-bold text-white">Junior</span>
                                <span class="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-bold">NOMINAL // 100%</span>
                            </div>
                        </div>
                    </div>

                    <div class="p-3 rounded-xl bg-slate-900/90 border border-rose-500/20 space-y-2">
                        <span class="text-[9px] uppercase text-slate-400 font-bold block tracking-wider">Ações Rápidas de Saúde</span>
                        <div class="grid grid-cols-2 gap-2">
                            <a href="http://localhost:8083" target="_blank" class="p-2 rounded-lg bg-rose-500/10 border border-rose-500/30 hover:bg-rose-500/20 text-rose-300 text-center font-bold text-[10px]">
                                + Marcar Consulta
                            </a>
                            <a href="http://localhost:8083" target="_blank" class="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 hover:bg-cyan-500/20 text-cyan-300 text-center font-bold text-[10px]">
                                Registar Exame
                            </a>
                        </div>
                    </div>
                `;
                break;

            case 'server':
                this.iconEl.innerText = '[#]';
                this.titleEl.innerText = 'Servidor AVA Server Linux // HUD';
                this.linkEl.href = 'http://localhost:9000';
                this.linkEl.querySelector('span').innerText = 'Abrir Portainer (:9000)';
                this.bodyEl.innerHTML = `
                    <div class="p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30 space-y-2">
                        <span class="text-[9px] uppercase text-emerald-300 font-bold block tracking-wider">Infraestrutura Homelab</span>
                        <div class="space-y-1 pt-1 text-[11px]">
                            <div class="flex justify-between border-b border-white/10 pb-1">
                                <span class="text-slate-400">Host IP:</span>
                                <span class="font-bold text-white font-mono">localhost (Tailscale)</span>
                            </div>
                            <div class="flex justify-between border-b border-white/10 py-1">
                                <span class="text-slate-400">Containers Docker:</span>
                                <span class="font-bold text-emerald-400">24 Ativos // 0 Pausados</span>
                            </div>
                            <div class="flex justify-between pt-1">
                                <span class="text-slate-400">Monitorização:</span>
                                <span class="font-bold text-cyan-300">Grafana & Prometheus ON</span>
                            </div>
                        </div>
                    </div>

                    <div class="p-3 rounded-xl bg-slate-900/90 border border-white/10 space-y-1.5">
                        <span class="text-[9px] uppercase text-slate-400 font-bold block tracking-wider">Serviços Chave</span>
                        <div class="text-[10px] space-y-1 text-slate-300">
                            <div>• <strong class="text-white">Portainer:</strong> Gestão de Stacks e Imagens (:9000)</div>
                            <div>• <strong class="text-white">Paperless-ngx:</strong> Indexação OCR de Documentos (:8000)</div>
                            <div>• <strong class="text-white">Nextcloud:</strong> Armazenamento e Sync Pessoal</div>
                            <div>• <strong class="text-white">Home Assistant:</strong> Automação Residencial</div>
                        </div>
                    </div>
                `;
                break;

            case 'workstation':
                this.iconEl.innerText = '[PC]';
                this.titleEl.innerText = 'Workstation Local // HUD';
                this.linkEl.href = 'http://127.0.0.1:8089/telemetry';
                this.linkEl.querySelector('span').innerText = 'Agente Telemetria (:8089)';
                this.bodyEl.innerHTML = `
                    <div class="p-3 rounded-xl bg-cyan-950/30 border border-cyan-500/30 space-y-2">
                        <span class="text-[9px] uppercase text-cyan-300 font-bold block tracking-wider">Node 01 Especificações</span>
                        <div class="space-y-1 pt-1 text-[11px]">
                            <div class="flex justify-between border-b border-white/10 pb-1">
                                <span class="text-slate-400">Sistema Operativo:</span>
                                <span class="font-bold text-white">Windows 11 Pro 64-bit</span>
                            </div>
                            <div class="flex justify-between border-b border-white/10 py-1">
                                <span class="text-slate-400">Processador:</span>
                                <span class="font-bold text-cyan-300">16 Cores // Multi-Thread</span>
                            </div>
                            <div class="flex justify-between border-b border-white/10 py-1">
                                <span class="text-slate-400">Placa Gráfica:</span>
                                <span class="font-bold text-violet-300">NVIDIA GeForce RTX 3070</span>
                            </div>
                            <div class="flex justify-between pt-1">
                                <span class="text-slate-400">Memória VRAM:</span>
                                <span class="font-bold text-violet-300">8.0 GB GDDR6</span>
                            </div>
                        </div>
                    </div>
                `;
                break;

            case 'fleet':
                this.iconEl.innerText = '[CAR]';
                this.titleEl.innerText = 'Frota & Garagem // HUD';
                this.linkEl.href = 'http://localhost:8082';
                this.linkEl.querySelector('span').innerText = 'Abrir Garagem (:8082)';
                this.bodyEl.innerHTML = `
                    <div class="p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30 space-y-2">
                        <span class="text-[9px] uppercase text-emerald-300 font-bold block tracking-wider">Viaturas Registadas</span>
                        <div class="space-y-1.5 pt-1 text-[11px]">
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <div>
                                    <strong class="text-white block">Sedan 2.0 TDI (AA-01-BB)</strong>
                                    <span class="text-[9px] text-slate-400 font-mono">170.600 km · 1.4 Gasoline (2003)</span>
                                </div>
                                <span class="text-[9px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold">IPO 30/11</span>
                            </div>
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <div>
                                    <strong class="text-white block">City Hatchback 1.2 (CC-02-DD)</strong>
                                    <span class="text-[9px] text-slate-400 font-mono">192.000 km · 1.9 TDI (2001)</span>
                                </div>
                                <span class="text-[9px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold">IPO 30/11</span>
                            </div>
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <div>
                                    <strong class="text-white block">Commuter 125cc (EE-03-FF)</strong>
                                    <span class="text-[9px] text-slate-400 font-mono">6.400 km · 125cc (2023)</span>
                                </div>
                                <span class="text-[9px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold">ISENTA IPO</span>
                            </div>
                        </div>
                    </div>
                `;
                break;

            case 'casa':
                this.iconEl.innerText = '[🏠]';
                this.titleEl.innerText = 'Casa, Warranties & Manutenção // HUD';
                this.linkEl.href = 'http://localhost:8084';
                this.linkEl.querySelector('span').innerText = 'Abrir Casa (:8084)';
                this.bodyEl.innerHTML = `
                    <div class="p-3 rounded-xl bg-cyan-950/30 border border-cyan-500/30 space-y-2">
                        <span class="text-[9px] uppercase text-cyan-300 font-bold block tracking-wider">Radar de Warranties Legais (3 Anos)</span>
                        <div class="space-y-1.5 pt-1 text-[11px]">
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <div>
                                    <strong class="text-white block">Membersung Galaxy Watch 8</strong>
                                    <span class="text-[9px] text-slate-400 font-mono">PCDIGA · Até Ago/2029</span>
                                </div>
                                <span class="text-[9px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold">1.088d</span>
                            </div>
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <div>
                                    <strong class="text-white block">Caldeira Mural Vulcano</strong>
                                    <span class="text-[9px] text-slate-400 font-mono">Até Out/2026</span>
                                </div>
                                <span class="text-[9px] px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold">50d</span>
                            </div>
                        </div>
                    </div>

                    <div class="p-3 rounded-xl bg-slate-900/90 border border-cyan-500/20 space-y-2">
                        <span class="text-[9px] uppercase text-slate-400 font-bold block tracking-wider">Ações Rápidas Domésticas</span>
                        <div class="grid grid-cols-2 gap-2">
                            <a href="http://localhost:8084" target="_blank" class="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 hover:bg-cyan-500/20 text-cyan-300 text-center font-bold text-[10px]">
                                + Equipamento
                            </a>
                            <a href="http://localhost:8084" target="_blank" class="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 hover:bg-emerald-500/20 text-emerald-300 text-center font-bold text-[10px]">
                                Maintenance
                            </a>
                        </div>
                    </div>
                `;
                break;

            case 'cidadania':
                this.iconEl.innerText = '[🪪]';
                this.titleEl.innerText = 'Citizenship & Taxes // HUD';
                this.linkEl.href = 'http://localhost:8085';
                this.linkEl.querySelector('span').innerText = 'Abrir Cidadania (:8085)';
                this.bodyEl.innerHTML = `
                    <div class="p-3 rounded-xl bg-purple-950/30 border border-purple-500/30 space-y-2">
                        <span class="text-[9px] uppercase text-purple-300 font-bold block tracking-wider">Documentos do Agregado</span>
                        <div class="space-y-1.5 pt-1 text-[11px]">
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <div>
                                    <strong class="text-white block">aa-stop-run // CC & Carta</strong>
                                    <span class="text-[9px] text-slate-400 font-mono">NIF 219606595</span>
                                </div>
                                <span class="text-[9px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold">VÁLIDO</span>
                            </div>
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <div>
                                    <strong class="text-white block">Member // CC & NISS</strong>
                                    <span class="text-[9px] text-slate-400 font-mono">NIF 225075830</span>
                                </div>
                                <span class="text-[9px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold">VÁLIDO</span>
                            </div>
                            <div class="p-2 rounded-lg bg-slate-900/90 border border-white/10 flex justify-between items-center">
                                <div>
                                    <strong class="text-white block">Pedro Junior // CC</strong>
                                    <span class="text-[9px] text-slate-400 font-mono">NIF 279828373</span>
                                </div>
                                <span class="text-[9px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold">VÁLIDO</span>
                            </div>
                        </div>
                    </div>

                    <div class="p-3 rounded-xl bg-slate-900/90 border border-purple-500/20 space-y-2">
                        <span class="text-[9px] uppercase text-slate-400 font-bold block tracking-wider">Tax Deadlines</span>
                        <div class="space-y-1 text-[10px] text-slate-300">
                            <div>• <strong class="text-white">e-fatura:</strong> Validação até 25 Fev</div>
                            <div>• <strong class="text-white">IRS Mod 3:</strong> Entrega até 30 Jun</div>
                            <div>• <strong class="text-white">IMI:</strong> Pagamento em Maio e Novembro</div>
                        </div>
                    </div>
                `;
                break;

            case 'calendar':
                this.iconEl.innerText = '[CAL]';
                this.titleEl.innerText = 'Agenda OS // Calendário Unificado';
                this.linkEl.href = 'http://localhost:8090/apps/calendar';
                this.linkEl.querySelector('span').innerText = 'Nextcloud Calendar (:8090)';
                
                const now = new Date();
                this.currentCalYear = this.currentCalYear || now.getFullYear();
                this.currentCalMonth = this.currentCalMonth || (now.getMonth() + 1);
                this.currentCalDayStr = this.currentCalDayStr || now.toISOString().slice(0, 10);
                
                this.loadAndRenderCalendar();
                break;
        }
    }

    async loadAndRenderCalendar() {
        if (!this.bodyEl) return;
        this.bodyEl.innerHTML = `
            <div class="p-6 text-center text-xs font-mono text-cyan-300 animate-pulse">
                [CARREGANDO // AGREGANDO EVENTOS DO ECOSSISTEMA...]
            </div>
        `;

        try {
            const res = await fetch(`/api/agenda?ano=${this.currentCalYear}&mes=${this.currentCalMonth}`);
            const data = await res.json();
            this.calendarData = data;
            this.renderCalendarUI(data);
        } catch (e) {
            this.bodyEl.innerHTML = `
                <div class="p-4 text-center text-xs text-rose-400 font-mono">
                    Falha ao carregar a agenda. Verifica a ligação ao servidor.
                </div>
            `;
        }
    }

    renderCalendarUI(data) {
        const ano = data.ano;
        const mes = data.mes;
        const mesNome = data.mes_nome;
        const diasComEventos = data.dias_com_eventos || {};
        const eventos = data.eventos || [];

        // Estrutura principal
        this.bodyEl.innerHTML = `
            <!-- Top Month Navigator Bar -->
            <div class="p-2 px-3 rounded-xl bg-slate-900/90 border border-violet-500/30 flex items-center justify-between font-mono text-xs shadow-lg">
                <button type="button" onclick="window.HUDDrawer.changeMonth(-1)" class="w-6 h-6 rounded-lg bg-slate-800 hover:bg-violet-950 border border-white/10 hover:border-violet-400 text-violet-300 flex items-center justify-center font-bold transition-all">
                    ‹
                </button>
                <div class="flex items-center space-x-2">
                    <span class="w-2 h-2 rounded-full bg-violet-400 animate-pulse"></span>
                    <span class="font-bold text-white uppercase tracking-wider">${mesNome} ${ano}</span>
                </div>
                <div class="flex items-center space-x-1">
                    <button type="button" onclick="window.HUDDrawer.goToday()" title="Ir para Hoje" class="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] font-bold border border-white/10">
                        Hoje
                    </button>
                    <button type="button" onclick="window.HUDDrawer.changeMonth(1)" class="w-6 h-6 rounded-lg bg-slate-800 hover:bg-violet-950 border border-white/10 hover:border-violet-400 text-violet-300 flex items-center justify-center font-bold transition-all">
                        ›
                    </button>
                    <button type="button" onclick="window.HUDDrawer.toggleQuickAdd()" class="px-2.5 py-1 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 hover:opacity-90 text-white text-[10px] font-bold shadow-md shadow-violet-500/20 ml-1">
                        + Evento
                    </button>
                </div>
            </div>

            <!-- Quick Add Event Form Modal / Box (Hidden by default) -->
            <div id="calendar-quick-add-box" class="hidden p-3 rounded-xl bg-slate-950/95 border border-violet-500/40 space-y-2 shadow-2xl transition-all">
                <div class="flex justify-between items-center border-b border-white/10 pb-1">
                    <span class="text-[10px] font-mono uppercase text-violet-300 font-bold tracking-wider">+ Novo Compromisso Familiar</span>
                    <button type="button" onclick="window.HUDDrawer.toggleQuickAdd()" class="text-slate-400 hover:text-white text-xs font-mono">[X]</button>
                </div>
                <div class="space-y-2 text-xs font-mono">
                    <input id="cal-new-title" type="text" placeholder="Título (ex: Jantar Família, Reunião...)" class="w-full bg-slate-900 border border-white/10 rounded-lg p-1.5 text-white placeholder-slate-500 focus:outline-none focus:border-violet-400">
                    <div class="grid grid-cols-2 gap-2">
                        <input id="cal-new-dt" type="datetime-local" class="bg-slate-900 border border-white/10 rounded-lg p-1.5 text-white focus:outline-none focus:border-violet-400 text-[11px]">
                        <select id="cal-new-type" class="bg-slate-900 border border-white/10 rounded-lg p-1.5 text-white focus:outline-none focus:border-violet-400 text-[11px]">
                            <option value="pessoal">Pessoal / Família</option>
                            <option value="trabalho">Trabalho / Projeto</option>
                            <option value="lazer">Lazer / Viagem</option>
                        </select>
                    </div>
                    <input id="cal-new-local" type="text" placeholder="Local (ex: Restaurante Central, Casa...)" class="w-full bg-slate-900 border border-white/10 rounded-lg p-1.5 text-white placeholder-slate-500 focus:outline-none focus:border-violet-400">
                    <div class="flex justify-end gap-2 pt-1">
                        <button type="button" onclick="window.HUDDrawer.toggleQuickAdd()" class="px-2 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700 text-[10px]">Cancel</button>
                        <button type="button" onclick="window.HUDDrawer.saveQuickEvent()" class="px-3 py-1 rounded bg-violet-600 hover:bg-violet-500 text-white font-bold text-[10px] shadow">Save</button>
                    </div>
                </div>
            </div>

            <!-- Month Calendar Matrix Grid -->
            <div class="p-2.5 rounded-xl bg-slate-900/80 border border-white/10 space-y-1.5">
                <!-- Weekday Headers -->
                <div class="grid grid-cols-7 gap-1 text-center font-mono text-[9px] uppercase tracking-wider text-slate-400 font-bold pb-1 border-b border-white/10">
                    <span>Seg</span><span>Ter</span><span>Qua</span><span>Qui</span><span>Sex</span><span class="text-violet-300">Sáb</span><span class="text-violet-300">Dom</span>
                </div>
                <!-- Days Grid -->
                <div id="calendar-days-grid" class="grid grid-cols-7 gap-1 text-center font-mono text-xs">
                    ${this.generateDaysGridHtml(ano, mes, diasComEventos)}
                </div>
            </div>

            <!-- Category Glow Dots Legend -->
            <div class="flex items-center justify-center space-x-3 text-[9px] font-mono text-slate-400 px-1">
                <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-rose-400 shadow-[0_0_6px_rgba(244,63,94,0.8)]"></span> Saúde</span>
                <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(16,185,129,0.8)]"></span> Veículos</span>
                <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_6px_rgba(6,182,212,0.8)]"></span> Finanças</span>
                <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-violet-400 shadow-[0_0_6px_rgba(139,92,246,0.8)]"></span> Pessoal</span>
            </div>

            <!-- Selected Day Timeline Panel -->
            <div class="p-3 rounded-xl bg-slate-900/90 border border-violet-500/20 space-y-2">
                <div class="flex justify-between items-center border-b border-white/10 pb-1.5">
                    <span id="calendar-timeline-header" class="text-[10px] font-mono uppercase text-violet-300 font-bold tracking-wider">
                        Compromissos // ${this.formatDisplayDate(this.currentCalDayStr)}
                    </span>
                    <span id="calendar-timeline-count" class="text-[9px] font-mono px-2 py-0.5 rounded bg-violet-500/20 text-violet-300 font-bold">
                        0 Eventos
                    </span>
                </div>
                <div id="calendar-timeline-list" class="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                    <!-- Populated by renderTimeline -->
                </div>
            </div>
        `;

        // Render timeline inicial para o dia selecionado
        this.renderTimeline(eventos, this.currentCalDayStr);
    }

    generateDaysGridHtml(ano, mes, diasComEventos) {
        const hojeStr = new Date().toISOString().slice(0, 10);
        
        // Primeiro dia do mês (0 = domingo, 1 = segunda, ..., 6 = sábado)
        const primeiroDia = new Date(ano, mes - 1, 1).getDay();
        // Converter para começar na segunda-feira (0 = Seg, ..., 6 = Dom)
        const offset = (primeiroDia === 0 ? 6 : primeiroDia - 1);
        
        const totalDias = new Date(ano, mes, 0).getDate();
        let html = '';

        // Células vazias do início
        for (let i = 0; i < offset; i++) {
            html += `<div class="p-1 h-9 rounded-lg bg-slate-950/30 opacity-20"></div>`;
        }

        // Dias do mês
        for (let d = 1; d <= totalDias; d++) {
            const dStr = String(d).padStart(2, '0');
            const mStr = String(mes).padStart(2, '0');
            const dataIso = `${ano}-${mStr}-${dStr}`;
            
            const isHoje = (dataIso === hojeStr);
            const isSelected = (dataIso === this.currentCalDayStr);
            const dots = diasComEventos[dataIso] || [];

            let borderClasses = 'border-white/5 bg-slate-950/60 text-slate-300 hover:border-violet-500/40 hover:bg-slate-800/80';
            if (isHoje) {
                borderClasses = 'border-cyan-400 bg-cyan-950/40 text-cyan-300 font-bold shadow-[0_0_8px_rgba(6,182,212,0.3)]';
            }
            if (isSelected) {
                borderClasses += ' ring-2 ring-violet-400 bg-violet-950/50';
            }

            // Gerar bolinhas de cores
            let dotsHtml = '';
            if (dots.length > 0) {
                dotsHtml = `<div class="flex justify-center items-center gap-0.5 mt-0.5">` +
                    dots.slice(0, 4).map(cor => {
                        let bg = 'bg-violet-400 shadow-[0_0_5px_rgba(139,92,246,0.8)]';
                        if (cor === 'rose') bg = 'bg-rose-400 shadow-[0_0_5px_rgba(244,63,94,0.8)]';
                        if (cor === 'emerald') bg = 'bg-emerald-400 shadow-[0_0_5px_rgba(16,185,129,0.8)]';
                        if (cor === 'cyan') bg = 'bg-cyan-400 shadow-[0_0_5px_rgba(6,182,212,0.8)]';
                        if (cor === 'sky') bg = 'bg-sky-400 shadow-[0_0_5px_rgba(56,189,248,0.8)]';
                        return `<span class="w-1 h-1 rounded-full ${bg}"></span>`;
                    }).join('') +
                    `</div>`;
            }

            html += `
                <div onclick="window.HUDDrawer.selectDay('${dataIso}')" class="p-1 h-9 rounded-lg border flex flex-col justify-between items-center cursor-pointer transition-all ${borderClasses}">
                    <span class="text-[11px] font-mono leading-none">${d}</span>
                    ${dotsHtml}
                </div>
            `;
        }

        return html;
    }

    selectDay(dataIso) {
        this.currentCalDayStr = dataIso;
        if (this.calendarData) {
            this.renderCalendarUI(this.calendarData);
        }
    }

    renderTimeline(todosEventos, dataAlvo) {
        const listEl = document.getElementById('calendar-timeline-list');
        const countEl = document.getElementById('calendar-timeline-count');
        const headerEl = document.getElementById('calendar-timeline-header');
        if (!listEl) return;

        // Filtrar eventos do dia específico
        const eventosDia = todosEventos.filter(e => e.data === dataAlvo);
        
        if (countEl) countEl.innerText = `${eventosDia.length} Evento(s)`;
        if (headerEl) headerEl.innerText = `Compromissos // ${this.formatDisplayDate(dataAlvo)}`;

        if (eventosDia.length === 0) {
            listEl.innerHTML = `
                <div class="py-4 text-center text-slate-500 font-mono text-[11px]">
                    Nenhum compromisso marcado para este dia.
                </div>
            `;
            return;
        }

        listEl.innerHTML = eventosDia.map(ev => {
            let corBadge = 'bg-violet-500/20 text-violet-300 border-violet-500/30';
            let corBorder = 'border-violet-500/20';
            if (ev.cor === 'rose') {
                corBadge = 'bg-rose-500/20 text-rose-300 border-rose-500/30';
                corBorder = 'border-rose-500/20';
            } else if (ev.cor === 'emerald') {
                corBadge = 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';
                corBorder = 'border-emerald-500/20';
            } else if (ev.cor === 'cyan') {
                corBadge = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30';
                corBorder = 'border-cyan-500/20';
            } else if (ev.cor === 'sky') {
                corBadge = 'bg-sky-500/20 text-sky-300 border-sky-500/30';
                corBorder = 'border-sky-500/20';
            }

            const editAttr = ev.editavel ? `onclick="if(window.AgendaModal) window.AgendaModal.openEdit(${JSON.stringify(ev).replace(/"/g, '&quot;')})" title="Clica para alterar este compromisso" style="cursor: pointer;"` : '';
            const deleteBtn = ev.editavel ? `
                <button type="button" onclick="event.stopPropagation(); window.HUDDrawer.deleteQuickEvent('${ev.id}')" title="Desmarcar / Remove" class="text-slate-500 hover:text-rose-400 hover:bg-rose-500/20 rounded px-1.5 py-0.5 text-xs font-mono transition-all">
                    ✕
                </button>
            ` : '';

            return `
                <div ${editAttr} class="p-2 rounded-xl bg-slate-950/80 border ${corBorder} flex items-center justify-between text-xs font-mono shadow-sm hover:border-violet-400/50 hover:bg-slate-900 transition-all">
                    <div class="flex items-center space-x-2.5 min-w-0">
                        <span class="px-1.5 py-0.5 rounded text-[10px] font-bold border shrink-0 ${corBadge}">
                            ${ev.hora}
                        </span>
                        <div class="truncate">
                            <strong class="text-white text-[11px] block truncate">${ev.titulo}</strong>
                            <span class="text-[9px] text-slate-400 block truncate">${ev.subtitulo || ev.local || 'Ecossistema AVA'}</span>
                        </div>
                    </div>
                    <div class="flex items-center space-x-1 shrink-0 ml-2">
                        ${deleteBtn}
                    </div>
                </div>
            `;
        }).join('');
    }

    changeMonth(delta) {
        this.currentCalMonth += delta;
        if (this.currentCalMonth > 12) {
            this.currentCalMonth = 1;
            this.currentCalYear += 1;
        } else if (this.currentCalMonth < 1) {
            this.currentCalMonth = 12;
            this.currentCalYear -= 1;
        }
        this.currentCalDayStr = `${this.currentCalYear}-${String(this.currentCalMonth).padStart(2, '0')}-01`;
        this.loadAndRenderCalendar();
    }

    goToday() {
        const now = new Date();
        this.currentCalYear = now.getFullYear();
        this.currentCalMonth = now.getMonth() + 1;
        this.currentCalDayStr = now.toISOString().slice(0, 10);
        this.loadAndRenderCalendar();
    }

    toggleQuickAdd() {
        const box = document.getElementById('calendar-quick-add-box');
        if (!box) return;
        box.classList.toggle('hidden');
        if (!box.classList.contains('hidden')) {
            const dtInput = document.getElementById('cal-new-dt');
            if (dtInput) {
                dtInput.value = `${this.currentCalDayStr}T10:00`;
            }
            const titleInput = document.getElementById('cal-new-title');
            if (titleInput) titleInput.focus();
        }
    }

    async saveQuickEvent() {
        const titleInput = document.getElementById('cal-new-title');
        const dtInput = document.getElementById('cal-new-dt');
        const typeSelect = document.getElementById('cal-new-type');
        const localInput = document.getElementById('cal-new-local');

        if (!titleInput || !titleInput.value.trim() || !dtInput || !dtInput.value) {
            alert('Por favor introduz o título e a data do evento.');
            return;
        }

        try {
            const res = await fetch('/api/agenda/evento', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    titulo: titleInput.value.trim(),
                    data_inicio: new Date(dtInput.value).toISOString(),
                    tipo: typeSelect ? typeSelect.value : 'pessoal',
                    local: localInput ? localInput.value.trim() : ''
                })
            });
            if (res.ok) {
                this.loadAndRenderCalendar();
            } else {
                alert('Erro ao guardar evento.');
            }
        } catch (e) {
            console.error(e);
            alert('Erro de rede ao guardar compromisso.');
        }
    }

    async deleteQuickEvent(id) {
        if (!confirm('Desejas desmarcar / remover este compromisso?')) return;
        try {
            const res = await fetch(`/api/agenda/evento/${id}`, { method: 'DELETE' });
            if (res.ok) {
                if (this.calendarData) {
                    await this.loadAndRenderCalendar();
                }
                if (window.location.pathname === '/' || window.location.pathname === '') {
                    setTimeout(() => window.location.reload(), 300);
                }
            } else {
                const err = await res.json().catch(() => ({}));
                alert(err.detail || 'Não foi possível remover este compromisso.');
            }
        } catch (e) {
            console.error(e);
            alert('Erro de comunicação ao remover compromisso.');
        }
    }

    formatDisplayDate(isoDateStr) {
        if (!isoDateStr) return '';
        const parts = isoDateStr.split('-');
        if (parts.length === 3) {
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        }
        return isoDateStr;
    }
}

window.HUDDrawer = new HUDDrawerManager();

