# Third-Party Notices

## wechatauto-replica

Repository: https://github.com/fanyuantaier/wechatauto-replica

Pinned commit: `04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d`  
License: Apache License 2.0

Used for low-level access to the local Windows WeChat database.

## rust-silk

Repository: https://github.com/Wangnov/rust-silk  
Version: `v0.1.3`  
License: BSD 3-Clause

The Windows build bundles `rust-silk.exe` to convert WeChat SILK voice data to WAV.
The build downloads the pinned Windows x64 release asset and verifies its SHA-256 before packaging it.

## sherpa-onnx

Repository: https://github.com/k2-fsa/sherpa-onnx  
Version used by this project: `1.13.6`  
License: Apache License 2.0

Used for optional local speech recognition.

## SenseVoice Small Int8 model

Model package:
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2

The model is not bundled in the repository or downloaded silently. When the user enables local voice transcription for the first time, the application asks for confirmation before downloading it. The application verifies `model.int8.onnx` with SHA-256:

`c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51`

If the model package contains its own LICENSE / README files, the installer keeps copies next to the installed model.
