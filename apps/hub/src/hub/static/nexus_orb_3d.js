/**
 * AVA Stark HUD 3.0 — High-Fidelity 3D Holographic Particle Core & Audio Visualizer
 * Scaled and styled with intense particle bloom, mechanical concentric rings,
 * audio frequency spectrum, and true Iron Man / Arc Reactor presence.
 * 
 * Optimized for 60 FPS performance on both Desktop and Mobile devices.
 */

class NexusOrb3DVisualizer {
    constructor(canvasId, spectrumCanvasId = 'soundwave-canvas') {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');

        this.spectrumCanvas = document.getElementById(spectrumCanvasId);
        this.spectrumCtx = this.spectrumCanvas ? this.spectrumCanvas.getContext('2d') : null;

        // Detect mobile capability
        this.isMobile = window.innerWidth < 768 || ('ontouchstart' in window && window.innerWidth < 1024);

        // Audio & State
        this.audioContext = null;
        this.analyser = null;
        this.dataArray = null;
        this.state = 'idle'; // 'idle' | 'listening' | 'thinking' | 'speaking'
        this.audioEnergy = 0;

        // 3D Engine Parameters
        this.fov = 320;
        this.time = 0;
        this.rotX = 0.15;
        this.rotY = 0;
        this.speedY = 0.009;

        // Interactive mouse parallax
        this.mouseX = 0;
        this.mouseY = 0;
        this.targetMouseX = 0;
        this.targetMouseY = 0;

        // 3D Particle Sphere (Streamlined for mobile)
        this.particles = [];
        this.numParticles = this.isMobile ? 75 : 280;
        this.sphereRadius = 115;

        // Concentric Mechanical Rings
        this.rings = this.isMobile ? [
            { radius: 110, angle: 0, speed: 0.012, tiltX: 0.35, tiltZ: 0.15, ticks: 12, arcSegments: 3, width: 1.5 },
            { radius: 135, angle: 0, speed: -0.008, tiltX: -0.25, tiltZ: -0.2, ticks: 16, arcSegments: 2, width: 2.0 },
            { radius: 155, angle: 0, speed: 0.005, tiltX: 0.18, tiltZ: 0.25, ticks: 12, arcSegments: 2, width: 1.2 }
        ] : [
            { radius: 145, angle: 0, speed: 0.012, tiltX: 0.35, tiltZ: 0.15, ticks: 36, arcSegments: 4, width: 2 },
            { radius: 175, angle: 0, speed: -0.008, tiltX: -0.25, tiltZ: -0.2, ticks: 48, arcSegments: 3, width: 2.5 },
            { radius: 205, angle: 0, speed: 0.005, tiltX: 0.18, tiltZ: 0.25, ticks: 24, arcSegments: 2, width: 1.5 }
        ];

        this.resize();
        this.initParticles();

        window.addEventListener('resize', () => {
            this.isMobile = window.innerWidth < 768 || ('ontouchstart' in window && window.innerWidth < 1024);
            this.numParticles = this.isMobile ? 75 : 280;
            this.resize();
            this.initParticles();
        });

        if (!this.isMobile) {
            this.canvas.addEventListener('mousemove', (e) => {
                const rect = this.canvas.getBoundingClientRect();
                this.targetMouseX = (e.clientX - rect.left - rect.width / 2) / (rect.width / 2);
                this.targetMouseY = (e.clientY - rect.top - rect.height / 2) / (rect.height / 2);
            });

            this.canvas.addEventListener('mouseleave', () => {
                this.targetMouseX = 0;
                this.targetMouseY = 0;
            });
        }

        this.animate = this.animate.bind(this);
        requestAnimationFrame(this.animate);
    }

    resize() {
        if (!this.canvas) return;
        const rect = this.canvas.parentElement.getBoundingClientRect();
        // Clamp DPR: on mobile clamp to 1.0 (eliminates 80% pixel fill cost), on desktop clamp to 1.5
        const dpr = this.isMobile ? 1.0 : Math.min(window.devicePixelRatio || 1, 1.5);

        this.canvas.width = Math.max(10, Math.floor(rect.width * dpr));
        this.canvas.height = Math.max(10, Math.floor(rect.height * dpr));
        this.ctx.setTransform(1, 0, 0, 1, 0, 0);
        this.ctx.scale(dpr, dpr);
        this.width = rect.width;
        this.height = rect.height;

        // Dynamically scale sphere radius to canvas height
        this.sphereRadius = Math.min(120, Math.max(75, rect.height * 0.28));
        this.rings[0].radius = this.sphereRadius * 1.30;
        this.rings[1].radius = this.sphereRadius * 1.58;
        this.rings[2].radius = this.sphereRadius * 1.85;

        if (this.spectrumCanvas) {
            const sRect = this.spectrumCanvas.parentElement.getBoundingClientRect();
            this.spectrumCanvas.width = Math.max(10, Math.floor(sRect.width * dpr));
            this.spectrumCanvas.height = Math.max(10, Math.floor(sRect.height * dpr));
            this.spectrumCtx.setTransform(1, 0, 0, 1, 0, 0);
            this.spectrumCtx.scale(dpr, dpr);
            this.spectrumWidth = sRect.width;
            this.spectrumHeight = sRect.height;
        }
    }

    initParticles() {
        this.particles = [];
        for (let i = 0; i < this.numParticles; i++) {
            const phi = Math.acos(1 - 2 * (i + 0.5) / this.numParticles);
            const theta = Math.PI * (1 + Math.sqrt(5)) * i;

            this.particles.push({
                baseX: Math.sin(phi) * Math.cos(theta),
                baseY: Math.sin(phi) * Math.sin(theta),
                baseZ: Math.cos(phi),
                size: 1.2 + Math.random() * 2.2,
                energyFactor: 0.8 + Math.random() * 0.4
            });
        }
    }

    setState(newState) {
        this.state = newState;
        const statusEl = document.getElementById('ava-voice-status');
        if (!statusEl) return;

        if (newState === 'listening') {
            statusEl.innerText = 'VOICE DETECTED // A ESCUTAR';
            statusEl.className = 'text-[11px] font-mono uppercase tracking-widest text-emerald-400 font-bold mb-0.5 hud-text-glow-emerald';
        } else if (newState === 'thinking') {
            statusEl.innerText = 'NEURAL INFERENCE // A PROCESSAR';
            statusEl.className = 'text-[11px] font-mono uppercase tracking-widest text-amber-400 font-bold mb-0.5 animate-pulse';
        } else if (newState === 'speaking') {
            statusEl.innerText = 'AUDIO SYNTHESIS // A RESPONDER';
            statusEl.className = 'text-[11px] font-mono uppercase tracking-widest text-cyan-300 font-bold mb-0.5 hud-text-glow';
        } else {
            statusEl.innerText = 'VOICE / AI STATUS';
            statusEl.className = 'text-[11px] font-mono uppercase tracking-widest text-cyan-400/90 font-bold mb-0.5 tracking-widest';
        }
    }

    async attachAudioStream(stream) {
        try {
            if (!this.audioContext) {
                this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }
            const source = this.audioContext.createMediaStreamSource(stream);
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 128;
            this.analyser.smoothingTimeConstant = 0.8;
            source.connect(this.analyser);
            this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
            this.setState('listening');
        } catch (e) {
            console.warn("Audio stream error:", e);
        }
    }

    setSpeakingState(active) {
        this.setState(active ? 'speaking' : 'idle');
    }

    animate() {
        // Pause animation completely if tab/screen is not visible to preserve mobile battery
        if (document.hidden) {
            requestAnimationFrame(this.animate);
            return;
        }

        const ctx = this.ctx;
        const w = this.width;
        const h = this.height;
        const cx = w / 2;
        const cy = h / 2;

        ctx.clearRect(0, 0, w, h);
        this.time += 0.02;

        // Smooth Parallax
        if (!this.isMobile) {
            this.mouseX += (this.targetMouseX - this.mouseX) * 0.06;
            this.mouseY += (this.targetMouseY - this.mouseY) * 0.06;
        }

        // Audio Frequency Capture
        let freqEnergy = 0;
        if (this.analyser && this.dataArray) {
            this.analyser.getByteFrequencyData(this.dataArray);
            let sum = 0;
            const count = Math.min(24, this.dataArray.length);
            for (let i = 0; i < count; i++) sum += this.dataArray[i];
            freqEnergy = (sum / count) / 255;
        }

        if (this.state === 'speaking') {
            freqEnergy = Math.max(freqEnergy, 0.45 + Math.sin(this.time * 8) * 0.35);
        } else if (this.state === 'thinking') {
            freqEnergy = Math.max(freqEnergy, 0.3 + Math.sin(this.time * 12) * 0.25);
        }

        this.audioEnergy += (freqEnergy - this.audioEnergy) * 0.15;

        // Rotations
        this.rotY += this.speedY + (this.state === 'listening' ? 0.02 : 0) + (this.state === 'thinking' ? 0.04 : 0);
        const curRotX = this.rotX + this.mouseY * 0.35;
        const curRotY = this.rotY + this.mouseX * 0.45;

        // --- 1. Multi-Layered Plasma Core Glow ---
        const rGlow = this.sphereRadius * (1.15 + this.audioEnergy * 0.45);
        const glowGrad = ctx.createRadialGradient(cx, cy, 10, cx, cy, rGlow * 1.4);

        if (this.state === 'thinking') {
            glowGrad.addColorStop(0, 'rgba(245, 158, 11, 0.65)');
            glowGrad.addColorStop(0.3, 'rgba(245, 158, 11, 0.3)');
            glowGrad.addColorStop(0.7, 'rgba(245, 158, 11, 0.08)');
            glowGrad.addColorStop(1, 'rgba(245, 158, 11, 0)');
        } else if (this.state === 'listening') {
            glowGrad.addColorStop(0, 'rgba(16, 185, 129, 0.6)');
            glowGrad.addColorStop(0.3, 'rgba(16, 185, 129, 0.25)');
            glowGrad.addColorStop(0.7, 'rgba(16, 185, 129, 0.06)');
            glowGrad.addColorStop(1, 'rgba(16, 185, 129, 0)');
        } else {
            glowGrad.addColorStop(0, 'rgba(6, 182, 212, 0.7)');
            glowGrad.addColorStop(0.35, 'rgba(6, 182, 212, 0.28)');
            glowGrad.addColorStop(0.7, 'rgba(6, 182, 212, 0.08)');
            glowGrad.addColorStop(1, 'rgba(6, 182, 212, 0)');
        }
        ctx.fillStyle = glowGrad;
        ctx.beginPath();
        ctx.arc(cx, cy, rGlow * 1.4, 0, Math.PI * 2);
        ctx.fill();

        // --- 2. Concentric Mechanical HUD Rings ---
        ctx.save();
        ctx.translate(cx, cy);

        this.rings.forEach((ring) => {
            ring.angle += ring.speed * (this.state === 'thinking' ? 2.5 : 1);

            ctx.save();
            ctx.scale(1, Math.cos(ring.tiltX + this.mouseY * 0.2));
            ctx.rotate(ring.angle);

            // Major Segmented Arcs
            ctx.beginPath();
            const segStep = (Math.PI * 2) / ring.arcSegments;
            for (let s = 0; s < ring.arcSegments; s++) {
                const startA = s * segStep;
                const endA = startA + segStep * 0.65;
                ctx.arc(0, 0, ring.radius, startA, endA);
            }

            let strokeColor = 'rgba(6, 182, 212, 0.45)';
            if (this.state === 'listening') strokeColor = 'rgba(16, 185, 129, 0.65)';
            if (this.state === 'thinking') strokeColor = 'rgba(245, 158, 11, 0.75)';
            if (this.state === 'speaking') strokeColor = 'rgba(34, 211, 238, 0.85)';

            ctx.strokeStyle = strokeColor;
            ctx.lineWidth = ring.width;
            
            // Only apply shadowBlur on desktop to protect mobile GPU framerate
            if (!this.isMobile) {
                ctx.shadowColor = strokeColor;
                ctx.shadowBlur = 6;
            }
            ctx.stroke();
            if (!this.isMobile) ctx.shadowBlur = 0;

            // Secondary fine ring
            ctx.beginPath();
            ctx.arc(0, 0, ring.radius - 4, 0, Math.PI * 2);
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
            ctx.lineWidth = 0.8;
            ctx.stroke();

            // Radial Calibration Ticks
            for (let t = 0; t < ring.ticks; t++) {
                const tickAngle = (t / ring.ticks) * Math.PI * 2;
                const isMajor = (t % 4 === 0);
                const len = isMajor ? 6 : 3;
                const tx1 = Math.cos(tickAngle) * (ring.radius - len / 2);
                const ty1 = Math.sin(tickAngle) * (ring.radius - len / 2);
                const tx2 = Math.cos(tickAngle) * (ring.radius + len / 2);
                const ty2 = Math.sin(tickAngle) * (ring.radius + len / 2);

                ctx.beginPath();
                ctx.moveTo(tx1, ty1);
                ctx.lineTo(tx2, ty2);
                ctx.strokeStyle = isMajor ? 'rgba(6, 182, 212, 0.85)' : 'rgba(255, 255, 255, 0.2)';
                ctx.lineWidth = isMajor ? 1.5 : 0.7;
                ctx.stroke();
            }

            ctx.restore();
        });
        ctx.restore();

        // --- 3. 3D Particle Sphere with Realistic Projection ---
        const projected = [];
        const dynamicR = this.sphereRadius * (1 + this.audioEnergy * 0.42 + Math.sin(this.time * 3) * 0.03);
        const cosY = Math.cos(curRotY);
        const sinY = Math.sin(curRotY);
        const cosX = Math.cos(curRotX);
        const sinX = Math.sin(curRotX);

        for (let i = 0; i < this.particles.length; i++) {
            const p = this.particles[i];

            const x = p.baseX * dynamicR;
            const y = p.baseY * dynamicR;
            const z = p.baseZ * dynamicR;

            // Rotate Y
            const x1 = x * cosY - z * sinY;
            const z1 = z * cosY + x * sinY;

            // Rotate X
            const y2 = y * cosX - z1 * sinX;
            const z2 = z1 * cosX + y * sinX;

            const scale = this.fov / (this.fov + z2);
            const screenX = cx + x1 * scale;
            const screenY = cy + y2 * scale;

            projected.push({
                x: screenX,
                y: screenY,
                z: z2,
                scale: scale,
                size: p.size * scale * (1 + this.audioEnergy * 0.5)
            });
        }

        // Only sort on desktop to avoid CPU overhead on mobile
        if (!this.isMobile) {
            projected.sort((a, b) => b.z - a.z);
        }

        for (let i = 0; i < projected.length; i++) {
            const pt = projected[i];
            const depthNorm = (pt.z + this.sphereRadius) / (this.sphereRadius * 2);
            const depthAlpha = Math.max(0.2, Math.min(1.0, depthNorm));

            ctx.beginPath();
            ctx.arc(pt.x, pt.y, Math.max(0.6, pt.size), 0, Math.PI * 2);

            if (this.state === 'thinking') {
                ctx.fillStyle = `rgba(245, 158, 11, ${depthAlpha * 0.95})`;
            } else if (this.state === 'listening') {
                ctx.fillStyle = `rgba(52, 211, 153, ${depthAlpha * 0.95})`;
            } else if (this.state === 'speaking') {
                ctx.fillStyle = `rgba(34, 211, 238, ${depthAlpha})`;
            } else {
                ctx.fillStyle = `rgba(6, 182, 212, ${depthAlpha * 0.9})`;
            }

            // High performance: no per-particle shadowBlur
            ctx.fill();

            // Dynamic Constellation Lines (Desktop only for peak fidelity)
            if (!this.isMobile && pt.z > 15 && i % 3 === 0 && i < projected.length - 2) {
                const nextPt = projected[i + 1];
                const dist = Math.hypot(pt.x - nextPt.x, pt.y - nextPt.y);
                if (dist < 40) {
                    ctx.beginPath();
                    ctx.moveTo(pt.x, pt.y);
                    ctx.lineTo(nextPt.x, nextPt.y);
                    ctx.strokeStyle = `rgba(6, 182, 212, ${0.25 * depthAlpha})`;
                    ctx.lineWidth = 0.8;
                    ctx.stroke();
                }
            }
        }

        // --- 4. Render Spectrum ---
        this.renderSpectrum();

        requestAnimationFrame(this.animate);
    }

    renderSpectrum() {
        if (!this.spectrumCtx || !this.spectrumCanvas) return;
        const sCtx = this.spectrumCtx;
        const sw = this.spectrumWidth;
        const sh = this.spectrumHeight;

        sCtx.clearRect(0, 0, sw, sh);

        const bars = this.isMobile ? 24 : 48;
        const barWidth = sw / bars;
        const midY = sh / 2;

        sCtx.beginPath();
        for (let i = 0; i < bars; i++) {
            let amp = 0.1;
            if (this.dataArray && i < this.dataArray.length) {
                amp = Math.max(amp, (this.dataArray[i] / 255));
            } else if (this.state === 'speaking') {
                amp = 0.2 + Math.sin(this.time * 6 + i * 0.35) * 0.4;
            } else if (this.state === 'listening') {
                amp = 0.15 + Math.sin(this.time * 4 + i * 0.25) * 0.3;
            } else {
                amp = 0.08 + Math.sin(this.time * 2.5 + i * 0.2) * 0.06;
            }

            const barHeight = Math.max(4, amp * (sh * 0.85));
            const x = i * barWidth;

            // Gradient bar
            if (this.state === 'listening') {
                sCtx.fillStyle = 'rgba(16, 185, 129, 0.85)';
            } else if (this.state === 'thinking') {
                sCtx.fillStyle = 'rgba(245, 158, 11, 0.85)';
            } else {
                sCtx.fillStyle = 'rgba(34, 211, 238, 0.85)';
            }

            sCtx.fillRect(x + 1.5, midY - barHeight / 2, Math.max(1, barWidth - 3), barHeight);
        }
    }
}

window.NexusOrb3DVisualizer = NexusOrb3DVisualizer;
window.NexusOrbVisualizer = NexusOrb3DVisualizer;
