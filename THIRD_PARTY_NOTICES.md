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

### rust-silk / SILK license text

BSD 3-Clause License

Copyright (c) 2006-2012, Skype Limited.  
Copyright (c) 2026, wangnov.  
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

## sherpa-onnx

Repository: https://github.com/k2-fsa/sherpa-onnx  
Version used by this project: `1.13.6`  
License: Apache License 2.0

Used for optional local speech recognition.

## SenseVoice Small Int8 model

Model package:
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2

The model is not bundled in the repository or downloaded silently. When the
user enables local voice transcription for the first time, the application
asks for confirmation before downloading it. The application verifies
`model.int8.onnx` with SHA-256:

`c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51`

If the model package contains its own LICENSE / README files, the installer
keeps copies next to the installed model.

## Apache License components

This repository's `LICENSE` file contains Apache License 2.0. It is included
in the Windows ZIP package together with this file.
