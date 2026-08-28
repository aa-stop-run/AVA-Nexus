/**
 * AVA Orbital Nexus 2.0 - Ultra-Premium 3D Holographic AI Voice Orb
 * Featuring 360-degree audio spectrum waves, fluid plasma shader simulation,
 * interactive particle gravity well, and real-time Web Audio API analysis.
 */

class NexusOrbVisualizer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        
        this.audioContext = null;
        this.analyser = null;
        this.dataArray = null;
        this.isListening = false;
        this.isSpeaking = false;
        this.audioEnergy = 0;
        
        this.time = 0;
        this.mouseX = 0;
        this.mouseY = 0;
        this.targetMouseX = 0;
        this.targetMouseY = 0;
        
        this.particles = [];
        this.numParticles = 90;
        
        this.resize();
        this.initParticles();
        
        window.addEventListener('resize', () => this.resize());
        
        this.canvas.addEventListener('mousemove', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            this.targetMouseX = (e.clientX - rect.left - rect.width / 2) / (rect.width / 2);
            this.targetMouseY = (e.clientY - rect.top - rect.height / 2) / (rect.height / 2);
        });
        
        this.canvas.addEventListener('mouseleave', () => {
            this.targetMouseX = 0;
            this.targetMouseY = 0;
        });
        
        this.animate = this.animate.bind(this);
        requestAnimationFrame(this.animate);
    }
    
    resize() {
        const rect = this.canvas.parentElement.getBoundingClientRect();
        this.canvas.width = rect.width * (window.devicePixelRatio || 1);
        this.canvas.height = rect.height * (window.devicePixelRatio || 1);
        this.ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
        this.displayWidth = rect.width;
        this.displayHeight = rect.height;
    }
    
    initParticles() {
        this.particles = [];
        for (let i = 0; i < this.numParticles; i++) {
            this.particles.push({
                angle: (i / this.numParticles) * Math.PI * 2,
                orbitRadius: 40 + Math.random() * 65,
                speed: 0.008 + (Math.random() - 0.5) * 0.012,
                orbitTilt: Math.random() * Math.PI,
                size: 1.2 + Math.random() * 2.2,
                color: i % 4 === 0 ? '#22d3ee' : (i % 4 === 1 ? '#34d399' : (i % 4 === 2 ? '#a78bfa' : '#38bdf8')),
                alpha: 0.4 + Math.random() * 0.6,
                pulseSpeed: 0.02 + Math.random() * 0.04
            });
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
            this.analyser.fftSize = 256;
            this.analyser.smoothingTimeConstant = 0.82;
            source.connect(this.analyser);
            this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
            this.isListening = true;
        } catch (e) {
            console.warn("Audio stream attach:", e);
        }
    }
    
    setSpeakingState(active) {
        this.isSpeaking = active;
    }
    
    animate() {
        const ctx = this.ctx;
        const w = this.displayWidth;
        const h = this.displayHeight;
        const cx = w / 2;
        const cy = h / 2;
        
        ctx.clearRect(0, 0, w, h);
        this.time += 0.02;
        
        // Smooth cursor parallax
        this.mouseX += (this.targetMouseX - this.mouseX) * 0.08;
        this.mouseY += (this.targetMouseY - this.mouseY) * 0.08;
        
        const centerOffsetX = cx + this.mouseX * 15;
        const centerOffsetY = cy + this.mouseY * 15;
        
        // 1. Audio Energy Calculation
        let currentEnergy = 0;
        if (this.analyser && this.dataArray) {
            this.analyser.getByteFrequencyData(this.dataArray);
            let sum = 0;
            for (let i = 0; i < 48; i++) {
                sum += this.dataArray[i];
            }
            currentEnergy = (sum / 48) / 255;
        } else if (this.isSpeaking) {
            currentEnergy = 0.45 + Math.sin(this.time * 4) * 0.25 + Math.sin(this.time * 9) * 0.15;
        } else {
            // Idle dynamic breathing
            currentEnergy = 0.08 + Math.sin(this.time * 0.8) * 0.05 + Math.cos(this.time * 1.6) * 0.02;
        }
        
        this.audioEnergy = this.audioEnergy * 0.75 + currentEnergy * 0.25;
        
        const baseRadius = Math.min(w, h) * 0.24;
        const coreRadius = baseRadius * (0.85 + this.audioEnergy * 0.35);
        
        // 2. Holographic Outer Corona Aura
        const coronaGrad = ctx.createRadialGradient(
            centerOffsetX, centerOffsetY, coreRadius * 0.3,
            centerOffsetX, centerOffsetY, coreRadius * 2.2
        );
        coronaGrad.addColorStop(0, 'rgba(6, 182, 212, 0.45)');
        coronaGrad.addColorStop(0.35, 'rgba(16, 185, 129, 0.22)');
        coronaGrad.addColorStop(0.7, 'rgba(139, 92, 246, 0.1)');
        coronaGrad.addColorStop(1, 'rgba(3, 7, 18, 0)');
        
        ctx.fillStyle = coronaGrad;
        ctx.beginPath();
        ctx.arc(centerOffsetX, centerOffsetY, coreRadius * 2.2, 0, Math.PI * 2);
        ctx.fill();
        
        // 3. 360-Degree Circular Frequency Spectrum Bars (JARVIS / Sci-Fi HUD)
        const numBars = 72;
        const spectrumRadius = coreRadius * 1.18;
        
        for (let i = 0; i < numBars; i++) {
            const angle = (i / numBars) * Math.PI * 2;
            let barVal = 0.1;
            
            if (this.dataArray && this.analyser) {
                const dataIndex = Math.floor((i % (numBars / 2)) / (numBars / 2) * 64);
                barVal = (this.dataArray[dataIndex] || 20) / 255;
            } else {
                barVal = 0.15 + Math.sin(angle * 6 + this.time * 2) * 0.12 + this.audioEnergy * 0.6;
            }
            
            const barLength = 6 + barVal * (35 + this.audioEnergy * 40);
            const x1 = centerOffsetX + Math.cos(angle) * spectrumRadius;
            const y1 = centerOffsetY + Math.sin(angle) * spectrumRadius;
            const x2 = centerOffsetX + Math.cos(angle) * (spectrumRadius + barLength);
            const y2 = centerOffsetY + Math.sin(angle) * (spectrumRadius + barLength);
            
            const barGrad = ctx.createLinearGradient(x1, y1, x2, y2);
            barGrad.addColorStop(0, 'rgba(6, 182, 212, 0.4)');
            barGrad.addColorStop(0.5, i % 2 === 0 ? 'rgba(52, 211, 153, 0.8)' : 'rgba(34, 211, 238, 0.9)');
            barGrad.addColorStop(1, 'rgba(167, 139, 250, 0.95)');
            
            ctx.strokeStyle = barGrad;
            ctx.lineWidth = 2.2;
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();
        }
        
        // 4. Concentric Harmonic Waveform Rings
        const numRings = 3;
        for (let r = 0; r < numRings; r++) {
            ctx.beginPath();
            const ringRadius = coreRadius * (0.92 + r * 0.16);
            ctx.strokeStyle = r === 0 ? 'rgba(34, 211, 238, 0.8)' : (r === 1 ? 'rgba(52, 211, 153, 0.6)' : 'rgba(167, 139, 250, 0.45)');
            ctx.lineWidth = 1.8 + this.audioEnergy * 2.5;
            
            const segments = 90;
            for (let i = 0; i <= segments; i++) {
                const theta = (i / segments) * Math.PI * 2;
                const wave1 = Math.sin(theta * 8 + this.time * (r % 2 === 0 ? 3 : -3)) * (4 + this.audioEnergy * 14);
                const wave2 = Math.cos(theta * 4 - this.time * 2) * (2 + this.audioEnergy * 8);
                const totalDist = ringRadius + wave1 + wave2;
                
                const px = centerOffsetX + Math.cos(theta) * totalDist;
                const py = centerOffsetY + Math.sin(theta) * totalDist;
                
                if (i === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
            }
            ctx.closePath();
            ctx.stroke();
        }
        
        // 5. Central Fluid Plasma Core
        const coreGrad = ctx.createRadialGradient(
            centerOffsetX - coreRadius * 0.25,
            centerOffsetY - coreRadius * 0.25,
            coreRadius * 0.05,
            centerOffsetX,
            centerOffsetY,
            coreRadius * 0.85
        );
        coreGrad.addColorStop(0, '#ffffff');
        coreGrad.addColorStop(0.25, '#67e8f9');
        coreGrad.addColorStop(0.55, '#06b6d4');
        coreGrad.addColorStop(0.85, '#0f766e');
        coreGrad.addColorStop(1, '#0284c7');
        
        ctx.save();
        ctx.shadowColor = '#22d3ee';
        ctx.shadowBlur = 35 + this.audioEnergy * 45;
        ctx.fillStyle = coreGrad;
        ctx.beginPath();
        ctx.arc(centerOffsetX, centerOffsetY, coreRadius * 0.76, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
        
        // 6. 3D Elliptical Orbiting Particles with Depth
        this.particles.forEach(p => {
            p.angle += p.speed * (1 + this.audioEnergy * 2.5);
            
            const cosA = Math.cos(p.angle);
            const sinA = Math.sin(p.angle);
            const tilt = p.orbitTilt;
            
            // 3D coordinates projection
            const px = centerOffsetX + cosA * p.orbitRadius * (1 + this.audioEnergy * 0.4);
            const py = centerOffsetY + sinA * p.orbitRadius * Math.cos(tilt) * (1 + this.audioEnergy * 0.4);
            const depth = sinA * Math.sin(tilt); // -1 (behind) to +1 (front)
            
            const scale = 0.7 + (depth + 1) * 0.35;
            const alpha = p.alpha * (0.4 + (depth + 1) * 0.3);
            
            ctx.fillStyle = p.color;
            ctx.globalAlpha = Math.max(0.1, Math.min(1.0, alpha));
            ctx.beginPath();
            ctx.arc(px, py, p.size * scale * (1 + this.audioEnergy * 0.6), 0, Math.PI * 2);
            ctx.fill();
        });
        ctx.globalAlpha = 1.0;
        
        requestAnimationFrame(this.animate);
    }
}

window.NexusOrbVisualizer = NexusOrbVisualizer;
