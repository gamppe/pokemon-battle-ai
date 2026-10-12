"""평가함수(가치망): 전투 상태 -> 내 승률.
포켓몬 토큰 6개를 범주형 임베딩(종, 특성, 도구, 기술 4개) + 수치 특징으로 만든 뒤 작은 트랜스포머로 섞고, 전역 벡터와 함께 승률 로짓을 낸다."""
import torch
import torch.nn as nn


class ValueNet(nn.Module):
    def __init__(self, vocab_sizes, n_num, n_glob, d=64, heads=4, layers=2, emb=16, drop=0.2):
        super().__init__()
        s = vocab_sizes
        self.e_species = nn.Embedding(s["species"], emb)
        self.e_ability = nn.Embedding(s["ability"], emb)
        self.e_item = nn.Embedding(s["item"], emb)
        self.e_move = nn.Embedding(s["move"], emb)
        self.tok = nn.Sequential(nn.Linear(emb * 4 + n_num, d), nn.GELU(), nn.Linear(d, d))
        self.pos = nn.Parameter(torch.zeros(6, d))          # 슬롯 위치(내 활성/내 벤치/상대 활성...)
        self.glob = nn.Sequential(nn.Linear(n_glob, d), nn.GELU())
        enc = nn.TransformerEncoderLayer(d, heads, dim_feedforward=d * 2, dropout=drop, batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(enc, layers)
        self.head = nn.Sequential(nn.LayerNorm(d * 3), nn.Dropout(drop), nn.Linear(d * 3, d), nn.GELU(), nn.Dropout(drop), nn.Linear(d, 1))
        self.base = nn.Linear(2, 1)          # 기준선: (HP 합 차이, 생존 수 차이) — 신경망은 이 위에 '나머지'만 학습한다
        self.edrop = nn.Dropout(drop)

    def forward(self, cat, num, glob):
        # cat: (B, 6, 7) long, num: (B, 6, n_num), glob: (B, n_glob)
        mv = self.e_move(cat[:, :, 3:7]).mean(dim=2)                     # 기술 4개 평균
        x = torch.cat([self.e_species(cat[:, :, 0]), self.e_ability(cat[:, :, 1]), self.e_item(cat[:, :, 2]), mv, num], dim=-1)
        x = self.edrop(self.tok(x)) + self.pos
        g = self.glob(glob).unsqueeze(1)
        h = self.enc(torch.cat([g, x], dim=1))                           # (B, 7, d)
        pooled = torch.cat([h[:, 0], h[:, 1], h[:, 4]], dim=-1)           # 전역, 내 활성, 상대 활성
        hp = num[:, :3, 0].sum(1) - num[:, 3:, 0].sum(1)
        alive = num[:, :3, 1].sum(1) - num[:, 3:, 1].sum(1)
        return self.base(torch.stack([hp, alive], dim=1)).squeeze(-1) + self.head(pooled).squeeze(-1)
