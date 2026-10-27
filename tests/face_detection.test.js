const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('face monitoring warns for zero or multiple faces and stops after recording', async () => {
    const alert = { style: {}, textContent: '' };
    const video = { paused: false, ended: false, readyState: 4 };
    const timers = new Map();
    let timerId = 0;
    let detector;
    class FakeFaceDetection {
        constructor(config) {
            this.config = config;
            detector = this;
        }
        setOptions(options) { this.options = options; }
        onResults(callback) { this.callback = callback; }
        async send({ image }) { assert.equal(image, video); }
    }
    const context = vm.createContext({
        console, FaceDetection: FakeFaceDetection,
        sessionStorage: { getItem() { return null; } },
        document: {
            addEventListener() {},
            getElementById(id) {
                return id === 'distractionAlert' ? alert : id === 'videoPreview' ? video : null;
            }
        },
        window: { addEventListener() {} },
        setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
        clearTimeout(id) { timers.delete(id); }
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'script.js'), 'utf8'), context);

    vm.runInContext('initializeFaceDetection(); startFaceDetection()', context);
    assert.equal(detector.options.model, 'short');
    assert.equal(detector.options.minDetectionConfidence, 0.5);
    assert.match(detector.config.locateFile('asset.wasm'), /@0\.4\.1646425229\/asset\.wasm$/);

    detector.callback({ detections: [] });
    assert.equal(alert.style.display, 'block');
    assert.match(alert.textContent, /No face detected/);
    detector.callback({ detections: [{}, {}] });
    assert.match(alert.textContent, /Multiple faces detected/);
    detector.callback({ detections: [{}] });
    assert.equal(alert.style.display, 'none');

    vm.runInContext('stopFaceDetection()', context);
    assert.equal(timers.size, 0);
    detector.callback({ detections: [] });
    assert.equal(alert.style.display, 'none');

    vm.runInContext('faceDetection = null; startFaceDetection()', context);
    assert.equal(alert.style.display, 'block');
    assert.match(alert.textContent, /Face monitoring is unavailable/);
});
