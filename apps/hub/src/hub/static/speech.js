// Stark HUD 3.0 Web Speech Engine for Voice Interaction with 3D Nexus Orb Visualizer
class AVASpeechEngine {
    constructor(visualizerInstance) {
        this.visualizer = visualizerInstance;
        this.isListening = false;
        this.synth = window.speechSynthesis;
        this.recognition = null;
        this.autoDismissTimer = null;
        window.avaSpeechEngine = this;
        if (this.synth && this.synth.onvoiceschanged !== undefined) {
            this.synth.onvoiceschanged = () => {
                if (this.synth) this.synth.getVoices();
            };
        }
        this.initRecognition();
    }

    initRecognition() {
        const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRec) {
            console.warn("Speech Recognition API não suportada neste browser.");
            return;
        }

        this.recognition = new SpeechRec();
        this.recognition.lang = 'pt-PT';
        this.recognition.continuous = false;
        this.recognition.interimResults = false;

        this.recognition.onstart = async () => {
            this.isListening = true;
            this.updateMicUI(true);
            if (this.visualizer && this.visualizer.setState) {
                this.visualizer.setState('listening');
            }
            if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia && this.visualizer) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    if (this.visualizer.attachAudioStream) {
                        this.visualizer.attachAudioStream(stream);
                    }
                } catch (e) {
                    console.log("Audio stream fallback:", e);
                }
            }
        };

        this.recognition.onresult = async (event) => {
            const transcript = event.results[0][0].transcript;
            this.handleUserQuery(transcript);
        };

        this.recognition.onerror = (event) => {
            console.warn("Erro no reconhecimento de voz:", event.error);
            this.updateMicUI(false);
            this.isListening = false;
            if (this.visualizer && this.visualizer.setState) {
                this.visualizer.setState('idle');
            }
        };

        this.recognition.onend = () => {
            this.updateMicUI(false);
            this.isListening = false;
        };
    }

    toggleListen() {
        if (!this.recognition) {
            const responseBox = document.getElementById('ava-ai-response-box');
            const responseText = document.getElementById('ava-ai-response-text');
            const queryEcho = document.getElementById('ava-user-query-echo');
            if (responseBox && responseText) {
                responseBox.classList.remove('hidden');
                if (queryEcho) queryEcho.innerText = "POLÍTICA DO BROWSER (HTTP)";
                responseText.innerHTML = `
                    <span class="text-amber-400 font-bold block mb-1">MICROFONE BLOQUEADO PELO NAVEGADOR:</span>
                    Os navegadores modernos apenas ativam reconhecimento de voz em conexões seguras (<strong>HTTPS</strong> ou <strong>localhost</strong>).<br>
                    Em ligações HTTP por IP (<code class="text-cyan-300">localhost</code>), podes usar a barra de comandos <strong>[Ctrl+K]</strong> abaixo.
                `;
                const input = document.getElementById('ava-command-input');
                if (input) input.focus();
            }
            return;
        }

        if (this.isListening) {
            this.recognition.stop();
        } else {
            this.recognition.start();
        }
    }

    updateMicUI(active) {
        const micBtn = document.getElementById('btn-mic');
        const micIndicator = document.getElementById('mic-indicator');

        if (micBtn) {
            if (active) {
                micBtn.classList.add('ring-4', 'ring-emerald-400', 'bg-emerald-500/40', 'animate-pulse');
                micBtn.classList.remove('border-cyan-400/50', 'bg-cyan-500/20');
            } else {
                micBtn.classList.remove('ring-4', 'ring-emerald-400', 'bg-emerald-500/40', 'animate-pulse');
                micBtn.classList.add('border-cyan-400/50', 'bg-cyan-500/20');
            }
        }
        if (micIndicator) {
            micIndicator.innerText = active ? 'A escutar a tua voz...' : 'Clica no núcleo para falar';
        }
    }

    async handleUserQuery(text) {
        if (!text || !text.trim()) return;
        const inputField = document.getElementById('ava-command-input');
        if (inputField) inputField.value = ''; // Limpar o campo de pesquisa após submissão

        if (this.visualizer && this.visualizer.setState) {
            this.visualizer.setState('thinking');
        }

        const responseBox = document.getElementById('ava-ai-response-box');
        const responseText = document.getElementById('ava-ai-response-text');
        const queryEcho = document.getElementById('ava-user-query-echo');

        if (this.autoDismissTimer) clearTimeout(this.autoDismissTimer);
        if (responseBox) responseBox.classList.remove('hidden');
        if (queryEcho) queryEcho.innerText = `"${text}"`;
        if (responseText) responseText.innerHTML = `<span class="animate-pulse text-amber-300 font-mono">[PROCESSANDO // CONSULTANDO MODELO IA...]</span>`;

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: text, session_id: 'default' })
            });
            const data = await res.json();
            const rawResponse = data.response || '';
            const actions = data.actions || [];
            
            if (responseText) {
                let htmlContent = this.formatMarkdown(rawResponse);

                // Renderizar Action Cards / Botões de Ação se existirem
                if (actions && actions.length > 0) {
                    htmlContent += `<div class="flex flex-wrap gap-2 mt-3 pt-2.5 border-t border-cyan-500/20">`;
                    for (const act of actions) {
                        if (act.type === 'call') {
                            htmlContent += `<a href="${act.target}" class="px-3 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/30 text-xs font-semibold flex items-center gap-1.5 transition-all no-underline shadow-sm"><span>${act.label}</span></a>`;
                        } else if (act.type === 'btn_query') {
                            const btnColor = act.style === 'danger' 
                                ? 'bg-rose-500/20 border-rose-500/40 text-rose-300 hover:bg-rose-500/30' 
                                : (act.style === 'warning' ? 'bg-amber-500/20 border-amber-500/40 text-amber-300 hover:bg-amber-500/30' : 'bg-cyan-500/20 border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/30');
                            htmlContent += `<button onclick="window.avaSpeechEngine.processQuery('${act.query.replace(/'/g, "\\'")}')" class="px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all cursor-pointer ${btnColor}">${act.label}</button>`;
                        } else if (act.type === 'link') {
                            htmlContent += `<a href="${act.target}" class="px-3 py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/20 text-xs font-semibold flex items-center gap-1.5 transition-all no-underline"><span>${act.label} ↗</span></a>`;
                        }
                    }
                    htmlContent += `</div>`;
                }
                responseText.innerHTML = htmlContent;
            }
            
            const cleanAudioText = this.cleanForSpeech(data.speech_text || rawResponse);
            this.speak(cleanAudioText);
        } catch (e) {
            if (responseText) responseText.innerText = "Desculpa aa-stop-run, ocorreu uma falha ao contactar a rede neural.";
            if (this.visualizer && this.visualizer.setState) {
                this.visualizer.setState('idle');
            }
        }
    }

    processQuery(queryText) {
        if (!queryText) return;
        this.handleAIInteraction(queryText);
    }

    formatMarkdown(text) {
        if (!text) return '';
        return text
            // Escape HTML para segurança
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            // Negrito com destaque ciano Stark HUD: **texto** ou __texto__
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-cyan-300 font-bold">$1</strong>')
            .replace(/__(.*?)__/g, '<strong class="text-cyan-300 font-bold">$1</strong>')
            // Itálico suave: *texto* ou _texto_
            .replace(/\*(.*?)\*/g, '<em class="text-cyan-100 italic">$1</em>')
            // Código inline: `código`
            .replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 rounded bg-slate-900 border border-cyan-500/30 text-cyan-300 font-mono text-[11px]">$1</code>')
            // Quebras de linha
            .replace(/\n/g, '<br>');
    }

    cleanForSpeech(text) {
        if (!text) return '';
        return text
            // Remove marcações markdown que o sintetizador leria em voz alta
            .replace(/\*\*/g, '')
            .replace(/\*/g, '')
            .replace(/__/g, '')
            .replace(/_/g, '')
            .replace(/`{1,3}[^`]*`{1,3}/g, '')
            .replace(/`/g, '')
            .replace(/#+\s*/g, '')
            .replace(/\[(.*?)\]\(.*?\)/g, '$1')
            .replace(/[•●■]/g, '')
            // Converte valores monetários para leitura humana natural em português
            .replace(/€\s*(\d+(?:[.,]\d+)?)/g, '$1 euros')
            .replace(/(\d+(?:[.,]\d+)?)\s*€/g, '$1 euros')
            // Remove emojis que causam ruído na voz
            .replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '')
            // Normaliza espaços
            .replace(/\s+/g, ' ')
            .trim();
    }

    getJarvisVoice() {
        if (!this.synth) return null;
        const voices = this.synth.getVoices() || [];
        if (!voices.length) return null;

        // Palavras-chave de vozes masculinas típicas (Windows / Chrome / Edge / Firefox)
        const maleKeywords = ['duarte', 'antonio', 'antónio', 'daniel', 'felipe', 'male', 'homem', 'pedro', 'manuel', 'george', 'ryan'];

        // 1. Voz Masculina em Português de Portugal (ex: Microsoft Duarte Natural)
        let voice = voices.find(v => (v.lang === 'pt-PT' || v.lang === 'pt_PT') && maleKeywords.some(k => v.name.toLowerCase().includes(k)));
        if (voice) return voice;

        // 2. Qualquer Voz Masculina em Português
        voice = voices.find(v => v.lang.startsWith('pt') && maleKeywords.some(k => v.name.toLowerCase().includes(k)));
        if (voice) return voice;

        // 3. Qualquer Voz em Português de Portugal
        voice = voices.find(v => v.lang === 'pt-PT' || v.lang === 'pt_PT');
        if (voice) return voice;

        // 4. Qualquer Voz em Português
        voice = voices.find(v => v.lang.startsWith('pt'));
        if (voice) return voice;

        // 5. Voz Britânica Masculina (Estilo Paul Bettany / JARVIS original)
        voice = voices.find(v => (v.lang === 'en-GB' || v.lang.startsWith('en')) && maleKeywords.some(k => v.name.toLowerCase().includes(k)));
        return voice || voices[0] || null;
    }

    isSpeaking() {
        return (this.currentAudio && !this.currentAudio.paused) || (this.synth && this.synth.speaking);
    }

    stop() {
        if (this.currentAudio) {
            try {
                this.currentAudio.pause();
                this.currentAudio.currentTime = 0;
            } catch (e) {}
            this.currentAudio = null;
        }
        if (this.synth) {
            try {
                this.synth.cancel();
            } catch (e) {}
        }
        if (this.visualizer && this.visualizer.setState) {
            this.visualizer.setState('idle');
        }
        if (this.autoDismissTimer) {
            clearTimeout(this.autoDismissTimer);
            this.autoDismissTimer = null;
        }
        this.updateBriefingButtonUI(false);
    }

    updateBriefingButtonUI(speaking) {
        const btn = document.getElementById('btn-speak-briefing');
        if (!btn) return;
        const label = document.getElementById('briefing-btn-label') || btn.querySelector('span.font-mono');
        const iconSvg = btn.querySelector('svg');

        if (speaking) {
            btn.classList.add('border-rose-400/70', 'bg-rose-500/30', 'text-rose-300', 'animate-pulse');
            btn.classList.remove('bg-cyan-500/20', 'border-cyan-400/40', 'text-cyan-300');
            btn.title = "Clique para parar / silenciar voz da AVA [ESC]";
            if (label) label.innerText = "Parar";
            if (iconSvg) {
                iconSvg.innerHTML = `<rect x="6" y="6" width="12" height="12" rx="2"></rect>`;
            }
        } else {
            btn.classList.remove('border-rose-400/70', 'bg-rose-500/30', 'text-rose-300', 'animate-pulse');
            btn.classList.add('bg-cyan-500/20', 'border-cyan-400/40', 'text-cyan-300');
            btn.title = "Ouvir Resumo Diário por Voz";
            if (label) label.innerText = "Briefing";
            if (iconSvg) {
                iconSvg.innerHTML = `<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path>`;
            }
        }
    }

    speak(text) {
        if (!text || !text.trim()) return;

        // Se já estiver a falar, um novo clique silencia imediatamente
        if (this.isSpeaking()) {
            this.stop();
            return;
        }

        const cleanText = this.cleanForSpeech(text);
        if (!cleanText) return;

        this.stop();

        if (this.visualizer && this.visualizer.setState) {
            this.visualizer.setState('speaking');
        }
        this.updateBriefingButtonUI(true);

        // 1. Prioridade Absoluta: Voz Neural Masculina JARVIS via /api/tts (pt-PT-DuarteNeural)
        const audioUrl = `/api/tts?text=${encodeURIComponent(cleanText)}&lang=pt`;
        const audio = new Audio(audioUrl);
        this.currentAudio = audio;

        audio.onended = () => {
            this.currentAudio = null;
            if (this.visualizer && this.visualizer.setState) {
                this.visualizer.setState('idle');
            }
            this.updateBriefingButtonUI(false);
            if (this.autoDismissTimer) clearTimeout(this.autoDismissTimer);
            this.autoDismissTimer = setTimeout(() => {
                const responseBox = document.getElementById('ava-ai-response-box');
                if (responseBox) responseBox.classList.add('hidden');
            }, 12000);
        };

        audio.onerror = (e) => {
            console.warn("TTS Neural do servidor falhou, a recorrer ao sintetizador do browser:", e);
            this.currentAudio = null;
            this.speakBrowserFallback(cleanText);
        };

        audio.play().catch(err => {
            console.warn("Autoplay impedido pelo navegador, a tentar síntese local:", err);
            this.speakBrowserFallback(cleanText);
        });
    }

    speakBrowserFallback(text) {
        if (!this.synth) {
            this.updateBriefingButtonUI(false);
            return;
        }
        this.synth.cancel();

        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = 'pt-PT';
        utter.pitch = 0.85;
        utter.rate = 1.0;

        const jarvisVoice = this.getJarvisVoice();
        if (jarvisVoice) utter.voice = jarvisVoice;

        utter.onstart = () => {
            if (this.visualizer && this.visualizer.setState) {
                this.visualizer.setState('speaking');
            }
            this.updateBriefingButtonUI(true);
        };
        utter.onend = () => {
            if (this.visualizer && this.visualizer.setState) {
                this.visualizer.setState('idle');
            }
            this.updateBriefingButtonUI(false);
            if (this.autoDismissTimer) clearTimeout(this.autoDismissTimer);
            this.autoDismissTimer = setTimeout(() => {
                const responseBox = document.getElementById('ava-ai-response-box');
                if (responseBox) responseBox.classList.add('hidden');
            }, 12000);
        };
        utter.onerror = () => {
            this.updateBriefingButtonUI(false);
        };

        this.synth.speak(utter);
    }
}

// Ouvinte global da tecla ESC para silenciar a fala instantaneamente
window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && window.speech && window.speech.isSpeaking && window.speech.isSpeaking()) {
        window.speech.stop();
    }
});

window.SpeechEngine = AVASpeechEngine;
