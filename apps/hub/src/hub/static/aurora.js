// Vibrant Living Aurora Canvas Shader & Real-time Audio Reactive Visualizer
class AuroraCanvas {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this.width = this.canvas.width = window.innerWidth;
        this.height = this.canvas.height = window.innerHeight;
        
        this.time = 0;
        this.audioLevel = 0;
        this.isVoiceActive = false;

        // Floating particles
        this.particles = [];
        for (let i = 0; i < 40; i++) {
            this.particles.push({
                x: Math.random() * this.width,
                y: Math.random() * this.height,
                radius: Math.random() * 2 + 1,
                speedX: (Math.random() - 0.5) * 0.4,
                speedY: (Math.random() - 0.5) * 0.4,
                opacity: Math.random() * 0.5 + 0.2,
                color: i % 3 === 0 ? 'rgba(6, 182, 212, ' : (i % 3 === 1 ? 'rgba(16, 185, 129, ' : 'rgba(139, 92, 246, ')
            });
        }
        
        window.addEventListener('resize', () => {
            this.width = this.canvas.width = window.innerWidth;
            this.height = this.canvas.height = window.innerHeight;
        });

        this.initAudio();
        this.animate();
    }

    initAudio() {
        this.audioCtx = null;
        this.analyser = null;
        this.dataArray = null;
    }

    async enableMicrophone() {
        try {
            if (!this.audioCtx) {
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                this.audioCtx = new AudioContext();
            }
            if (this.audioCtx.state === 'suspended') {
                await this.audioCtx.resume();
            }
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const source = this.audioCtx.createMediaStreamSource(stream);
            this.analyser = this.audioCtx.createAnalyser();
            this.analyser.fftSize = 64;
            source.connect(this.analyser);
            this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
            this.isVoiceActive = true;
            return true;
        } catch (e) {
            console.warn("Microphone access not available:", e);
            return false;
        }
    }

    getAudioEnergy() {
        if (!this.analyser || !this.dataArray) return 0;
        this.analyser.getByteFrequencyData(this.dataArray);
        let sum = 0;
        for (let i = 0; i < this.dataArray.length; i++) {
            sum += this.dataArray[i];
        }
        return sum / this.dataArray.length / 255;
    }

    simulatePulse(intensity = 0.6) {
        this.audioLevel = Math.max(this.audioLevel, intensity);
    }

    drawAuroraRibbon(baseY, amplitude, freq, speed, colorStop1, colorStop2, colorStop3) {
        const ctx = this.ctx;
        ctx.save();
        
        const grad = ctx.createLinearGradient(0, 0, this.width, this.height);
        grad.addColorStop(0, colorStop1);
        grad.addColorStop(0.5, colorStop2);
        grad.addColorStop(1, colorStop3);
        
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.moveTo(0, this.height);
        ctx.lineTo(0, baseY);

        const currentAmp = amplitude * (1 + this.audioLevel * 3.5);
        const currentFreq = freq * (1 + this.audioLevel * 0.4);

        for (let x = 0; x <= this.width; x += 12) {
            const y = baseY + 
                      Math.sin(x * currentFreq + this.time * speed) * currentAmp +
                      Math.cos(x * currentFreq * 0.6 - this.time * speed * 0.7) * (currentAmp * 0.7) +
                      Math.sin(x * 0.001 + this.time * 0.2) * 25;
            ctx.lineTo(x, y);
        }

        ctx.lineTo(this.width, this.height);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
    }

    animate() {
        this.time += 0.012;

        // Audio Reactivity
        const realEnergy = this.getAudioEnergy();
        if (realEnergy > 0.04) {
            this.audioLevel = realEnergy;
        } else {
            this.audioLevel *= 0.94;
        }

        // Deep rich background
        const bgGrad = this.ctx.createRadialGradient(
            this.width / 2, this.height * 0.3, 50,
            this.width / 2, this.height / 2, this.width
        );
        bgGrad.addColorStop(0, '#0a1020');
        bgGrad.addColorStop(0.6, '#060a14');
        bgGrad.addColorStop(1, '#03050a');
        
        this.ctx.fillStyle = bgGrad;
        this.ctx.fillRect(0, 0, this.width, this.height);

        // Floating particles
        for (let p of this.particles) {
            p.x += p.speedX * (1 + this.audioLevel * 2);
            p.y += p.speedY * (1 + this.audioLevel * 2);
            if (p.x < 0) p.x = this.width;
            if (p.x > this.width) p.x = 0;
            if (p.y < 0) p.y = this.height;
            if (p.y > this.height) p.y = 0;

            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.radius * (1 + this.audioLevel * 1.5), 0, Math.PI * 2);
            this.ctx.fillStyle = p.color + (p.opacity * (1 + this.audioLevel)) + ')';
            this.ctx.fill();
        }

        // Glowing Aurora Ribbons (Vibrant Layers)
        this.drawAuroraRibbon(
            this.height * 0.50, 
            90, 
            0.0015, 
            1.2, 
            'rgba(6, 182, 212, 0.18)', 
            'rgba(59, 130, 246, 0.14)', 
            'rgba(139, 92, 246, 0.12)'
        );

        this.drawAuroraRibbon(
            this.height * 0.65, 
            75, 
            0.0022, 
            1.6, 
            'rgba(16, 185, 129, 0.22)', 
            'rgba(6, 182, 212, 0.18)', 
            'rgba(16, 185, 129, 0.10)'
        );

        this.drawAuroraRibbon(
            this.height * 0.78, 
            60, 
            0.0030, 
            2.0, 
            'rgba(139, 92, 246, 0.25)', 
            'rgba(244, 63, 94, 0.12)', 
            'rgba(6, 182, 212, 0.15)'
        );

        requestAnimationFrame(() => this.animate());
    }
}

window.AuroraEngine = AuroraCanvas;
