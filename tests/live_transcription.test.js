const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('audio worklet emits a three-second PCM chunk', () => {
    let Processor;
    const posted = [];
    class FakeProcessor {
        constructor() {
            this.port = { postMessage(buffer) { posted.push(buffer); } };
        }
    }
    const worklet = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'live-whisper-worklet.js'), 'utf8');
    vm.runInNewContext(worklet, {
        AudioWorkletProcessor: FakeProcessor,
        Float32Array,
        sampleRate: 16000,
        registerProcessor(name, implementation) {
            assert.equal(name, 'live-whisper-chunks');
            Processor = implementation;
        }
    });
    const processor = new Processor({ processorOptions: { chunkSeconds: 3 } });
    for (let i = 0; i < 375; i++) {
        processor.process([[new Float32Array(128).fill(0.1)]]);
    }
    assert.equal(posted.length, 1);
    assert.equal(posted[0].byteLength, 3 * 16000 * 4);
    for (let i = 0; i < 188; i++) {
        processor.process([[new Float32Array(128).fill(0.1)]]);
    }
    processor.port.onmessage({ data: { type: 'flush' } });
    assert.equal(posted.length, 3);
    assert.equal(posted[1].byteLength, 188 * 128 * 4);
    assert.equal(posted[2].type, 'flushed');
});

test('live Whisper text appears during recording and stops updating afterward', async () => {
    let requests = 0;
    let workletNode;
    const answer = { innerText: '' };
    class FakeAudioContext {
        constructor() {
            this.sampleRate = 16000;
            this.destination = {};
            this.audioWorklet = { addModule: async (file) => assert.equal(file, 'live-whisper-worklet.js') };
        }
        createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
        async resume() {}
        async close() {}
    }
    class FakeAudioWorkletNode {
        constructor() {
            this.port = { onmessage: null };
            workletNode = this;
        }
        connect() {}
        disconnect() {}
    }
    const context = vm.createContext({
        Blob, FormData, URL, AbortController, Float32Array, console,
        MediaStream: class { constructor(tracks) { this.tracks = tracks; } },
        AudioWorkletNode: FakeAudioWorkletNode,
        answer,
        document: { addEventListener() {} },
        window: { addEventListener() {}, AudioContext: FakeAudioContext },
        sessionStorage: { getItem() { return null; } },
        fetch: async () => {
            requests++;
            return { ok: true, json: async () => ({ text: 'Hello from Whisper' }) };
        }
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'script.js'), 'utf8'), context);
    vm.runInContext(`
        answerText = answer;
        questionIndex = 0;
        mediaRecorder = { state: 'recording' };
    `, context);
    await vm.runInContext('startLiveTranscription({ kind: "audio" }, 0)', context);
    assert.match(answer.innerText, /live captions will appear/);
    workletNode.port.onmessage({ data: new Float32Array([0.2]).buffer });
    await vm.runInContext('liveTranscriptionSession.queue', context);
    assert.equal(answer.innerText, 'Hello from Whisper');
    vm.runInContext('stopLiveTranscription()', context);
    assert.equal(requests, 1);
});

test('finishing a recording keeps the last caption in the answer history', async () => {
    let workletNode;
    let calls = 0;
    const answer = { innerText: '' };
    const items = new Map();
    const history = {
        parentElement: { style: {} },
        querySelector(selector) { return items.get(Number(selector.match(/\d+/)[0])) || null; },
        append(item) { items.set(Number(item.dataset.answerIndex), item); }
    };
    class FakeAudioContext {
        constructor() {
            this.sampleRate = 16000;
            this.destination = {};
            this.audioWorklet = { addModule: async () => {} };
        }
        createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
        async resume() {}
        async close() {}
    }
    class FakeNode {
        constructor() {
            this.port = {
                onmessage: null,
                postMessage(message) {
                    if (message.type === 'flush') {
                        queueMicrotask(() => {
                            this.onmessage({ data: new Float32Array([0.3]).buffer });
                            this.onmessage({ data: { type: 'flushed' } });
                        });
                    }
                }
            };
            workletNode = this;
        }
        connect() {}
        disconnect() {}
    }
    const context = vm.createContext({
        Blob, FormData, URL, AbortController, Float32Array, console, queueMicrotask,
        setTimeout, clearTimeout,
        MediaStream: class { constructor(tracks) { this.tracks = tracks; } },
        AudioWorkletNode: FakeNode,
        answer,
        document: {
            addEventListener() {},
            createElement() {
                return {
                    dataset: {}, children: [],
                    append(...children) { this.children.push(...children); },
                    querySelector(selector) {
                        return this.children.find(child => `.${child.className}` === selector);
                    }
                };
            }
        },
        window: { addEventListener() {}, AudioContext: FakeAudioContext },
        sessionStorage: { getItem() { return null; } },
        fetch: async () => ({ ok: true, json: async () => ({ text: `part ${++calls}` }) })
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'script.js'), 'utf8'), context);
    context.history = history;
    vm.runInContext(`
        answerText = answer;
        answerHistory = history;
        questionIndex = 0;
        mediaRecorder = { state: 'recording' };
    `, context);
    await vm.runInContext('startLiveTranscription({ kind: "audio" }, 0)', context);
    workletNode.port.onmessage({ data: new Float32Array([0.2]).buffer });
    await vm.runInContext('liveTranscriptionSession.queue', context);
    const finalText = vm.runInContext('finishLiveTranscription()', context);
    vm.runInContext('questionIndex = 1', context);
    assert.equal(await finalText, 'part 1 part 2');
    assert.equal(items.get(0).querySelector('.answer-history-text').textContent, 'part 1 part 2');
});
