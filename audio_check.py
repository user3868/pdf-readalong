#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_check.py —— 从音频本身判断"有没有两个声音同时响"
三路证据：
 ① 波形/能量：找出高能量段（两声叠加会明显抬高）
 ② 基频（F0）与"双基频"检测：单声道里若同时存在两条不同基频轨迹 → 两个人在说话
 ③ 语音转文字（FunASR）：同一时间窗若转出"两句话混在一起"的乱码 → 声音相撞
另外输出一张图（波形 + 频谱 + F0 + 双基频标记）供目视。
"""
import json
import os
import subprocess
import sys
import wave

import librosa
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

FF = r'C:\ProgramData\chocolatey\bin\ffmpeg.exe'
OUTDIR = os.path.dirname(os.path.abspath(__file__))
SR = 16000


def extract(mp4):
    wav = os.path.join(OUTDIR, '_check_audio.wav')
    subprocess.run([FF, '-y', '-v', 'error', '-i', mp4, '-ac', '1', '-ar', str(SR),
                    '-c:a', 'pcm_s16le', wav], check=True)
    y, _ = librosa.load(wav, sr=SR, mono=True)
    return y


def double_pitch(y, sr=SR, hop=160, frame=512):
    """逐帧自相关找所有强周期峰：>=2 个 → 疑似两个声音同时说"""
    flags = []
    f0s = []
    n = 1 + (len(y) - frame) // hop
    for i in range(n):
        seg = y[i * hop:i * hop + frame]
        if np.sqrt(np.mean(seg ** 2)) < 0.01:
            flags.append(0); f0s.append(0.0); continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, 'full')[len(seg) - 1:]
        ac /= (ac[0] + 1e-9)
        lo, hi = int(sr / 400), int(sr / 70)          # 70~400Hz 的人声基频范围
        if hi >= len(ac):
            hi = len(ac) - 1
        peaks = []
        for k in range(lo + 1, hi - 1):
            if ac[k] > ac[k - 1] and ac[k] >= ac[k + 1] and ac[k] > 0.45:
                peaks.append((ac[k], sr / k))
        peaks.sort(reverse=True)
        strong = [p for p in peaks if p[0] > 0.45]
        f0s.append(strong[0][1] if strong else 0.0)
        flags.append(len(strong))
    return np.array(f0s), np.array(flags)


def asr(wav):
    try:
        from funasr import AutoModel
        m = AutoModel(model='paraformer-zh', device='cpu', disable_update=True, disable_pbar=True)
        r = m.generate(input=wav, batch_size_s=60, return_raw_text=True)
        return r
    except Exception as e:
        return 'ASR 失败: %s: %s' % (type(e).__name__, e)


def main(mp4):
    y = extract(mp4)
    dur = len(y) / SR
    print('音频时长 %.1f 秒' % dur)
    hop = 160
    f0, npeaks = double_pitch(y)
    times = np.arange(len(f0)) * hop / SR
    # 统计
    voiced = f0 > 0
    print('有声帧 %d / %d（%.0f%%）' % (voiced.sum(), len(f0), 100 * voiced.mean()))
    susp = npeaks >= 2
    print('"疑似双声"帧（同一帧检出 ≥2 个强周期峰）：%d（%.1f%%）' % (susp.sum(), 100 * susp.mean()))
    # 连续片段
    runs = []
    i = 0
    while i < len(susp):
        if susp[i]:
            j = i
            while j + 1 < len(susp) and susp[j + 1]:
                j += 1
            if j - i >= 4:                       # ≥5 帧（约 50ms）
                runs.append((times[i], times[j], float(np.mean(f0[i:j + 1][f0[i:j + 1] > 0])) if (f0[i:j+1] > 0).any() else 0))
            i = j + 1
        else:
            i += 1
    print('\n疑似双声连续片段（≥50ms）：%d 段' % len(runs))
    for a, b, f in runs[:20]:
        print('   %6.2f → %6.2f s  (F0≈%.0f Hz)' % (a, b, f))

    # 能量
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0]
    trms = np.arange(len(rms)) * hop / SR
    thr = np.percentile(rms, 95) * 0.6
    loud = rms > thr
    print('\n高能量段（用于对照：两声叠加会明显更高）')
    i = 0
    while i < len(loud):
        if loud[i]:
            j = i
            while j + 1 < len(loud) and loud[j + 1]:
                j += 1
            if (j - i) * hop / SR > 0.3:
                print('   %6.2f → %6.2f s  RMS=%.3f' % (trms[i], trms[j], float(np.max(rms[i:j + 1]))))
            i = j + 1
        else:
            i += 1

    # 图：波形 + 频谱 + F0 + 双声标记
    fig, ax = plt.subplots(3, 1, figsize=(16, 11), sharex=True)
    tt = np.arange(len(y)) / SR
    ax[0].plot(tt, y, lw=0.4, color='#2b6cb0')
    ax[0].set_ylabel('waveform')
    ax[0].set_title('waveform (peaks = loud; two voices overlap -> taller/messier)')
    D = librosa.amplitude_to_db(np.abs(librosa.stft(y, n_fft=1024, hop_length=hop)), ref=np.max)
    img = librosa.display.specshow(D, sr=SR, hop_length=hop, x_axis='time', y_axis='log', ax=ax[1], cmap='magma')
    ax[1].set_title('spectrogram (two voices -> two parallel harmonic stacks)')
    ax[2].plot(times, f0, lw=0.8, color='#2f855a', label='F0 (dominant)')
    ax[2].scatter(times[susp], f0[susp], s=6, color='red', label='suspected double-voice frames')
    ax[2].set_ylim(60, 420); ax[2].set_xlabel('seconds'); ax[2].legend(loc='upper right')
    ax[2].set_title('F0 track + double-voice flags')
    png = os.path.join(OUTDIR, '_audio_report.png')
    plt.tight_layout(); plt.savefig(png, dpi=90)
    print('\n图: %s' % png)

    # 分段转文字
    print('\n分段语音转文字（检查是否出现"两句话混在一起"）：')
    win = 6.0
    n = int(dur // win) + 1
    for k in range(n):
        a, b = k * win, min(dur, (k + 1) * win)
        seg = y[int(a * SR):int(b * SR)]
        if len(seg) < SR:
            break
        w = os.path.join(OUTDIR, '_seg.wav')
        with wave.open(w, 'wb') as fh:
            fh.setnchannels(1); fh.setsampwidth(2); fh.setframerate(SR)
            fh.writeframes((seg * 32767).astype(np.int16).tobytes())
        r = asr(w)
        txt = ''
        if isinstance(r, list) and r:
            txt = r[0].get('text') or r[0].get('raw_text') or str(r[0])
        else:
            txt = str(r)
        print('  [%5.1f-%5.1f] %s' % (a, b, txt[:90]))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUTDIR, '演示_全流程.mp4'))
