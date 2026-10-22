import sys
import os
import torch

sys.path.append(f"{os.getcwd()}/GPT_SoVITS/eres2net")
sv_path = "GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt"
from ERes2NetV2 import ERes2NetV2
import kaldi as Kaldi


class SV:
    def __init__(self, device, is_half):
        pretrained_state = torch.load(sv_path, map_location="cpu", weights_only=False)
        embedding_model = ERes2NetV2(baseWidth=24, scale=4, expansion=4)
        embedding_model.load_state_dict(pretrained_state)
        embedding_model.eval()
        self.embedding_model = embedding_model
        if is_half == False:
            self.embedding_model = self.embedding_model.to(device)
        else:
            self.embedding_model = self.embedding_model.half().to(device)
        self.is_half = is_half

    def compute_embedding3(self, wav):
        # TachiTalk: keep one reference only; never cache generated speech.
        # Holding the tensor itself also prevents an id from being reused.
        key = (wav._version, wav.device, wav.dtype, self.is_half, id(self.embedding_model))
        if getattr(self, "_cached_wav", None) is wav and self._cached_key == key:
            return self._cached_embedding
        with torch.no_grad():
            if self.is_half == True:
                wav = wav.half()
            feat = torch.stack(
                [Kaldi.fbank(wav0.unsqueeze(0), num_mel_bins=80, sample_frequency=16000, dither=0) for wav0 in wav]
            )
            sv_emb = self.embedding_model.forward3(feat)
        self._cached_wav, self._cached_key, self._cached_embedding = wav, key, sv_emb
        return sv_emb
