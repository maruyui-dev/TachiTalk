# Third-party notices

The root MIT license covers original TachiTalk code. It does not relicense
dependencies, pretrained weights, character artwork, or reference recordings.

| Component | Upstream / license information |
| --- | --- |
| GPT-SoVITS inference code | [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS), MIT; retain `services/gpt_sovits/LICENSE` and `THIRD_PARTY_NOTICES.txt` |
| PySide6 / Qt / Shiboken | [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html); LGPLv3 / GPL alternatives. Windows builds use dynamically loaded libraries. Relevant installed license files are copied into `licenses/` in the release. |
| PyTorch / torchaudio / torchvision | [PyTorch](https://github.com/pytorch/pytorch); retain the licenses and dependency notices included in the private runtime |
| CUDA / cuDNN libraries | NVIDIA redistributable binaries under their respective terms; retain bundled notices. NVIDIA drivers are installed separately. |
| Microsoft Visual C++ runtime | The MSVC 14.x redistributable DLLs supplied with Qt for Python are retained in the client and provided app-locally to the inference Python. They retain Microsoft's copyright and distribution terms, independently of MIT; see [Microsoft deployment documentation](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files). |
| GPT-SoVITS pretrained components and other runtime packages | Each component retains its own model card, license and distribution metadata; see `services/gpt_sovits/` and its runtime |
| Character portraits, reference recordings and character voice weights | Local user-provided character resources. These are outside TachiTalk's MIT grant; original creators and rightsholders retain their rights. Do not treat the code license as authorization to redistribute or commercially exploit them. |

Release archives preserve the upstream license files. Source is available from
this repository and the upstream links above; the Qt libraries are separate
files and can be replaced with compatible builds. No additional restriction on
reverse engineering for debugging modifications to LGPL components is imposed.
