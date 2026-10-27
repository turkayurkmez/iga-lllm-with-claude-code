"""Gömme katmanı sözleşmesi (docs/rag.md §4). Ağa çıkmaz, `.env` gerektirmez.

Voyage istemcisi sahte nesneyle verilir; bekleme (`sleep`) monkeypatch'lenir.
"""

import importlib.util
import math
from types import SimpleNamespace

import pytest

from backend.rag import embed
from backend.rag.embed import (
    BATCH_SIZE,
    MAX_ATTEMPTS,
    EmbedConfigError,
    EmbedError,
    embed_documents,
    embed_query,
)

MODEL = "sahte-gomme-modeli"


class RateLimit(Exception):
    """Voyage SDK'sının 429 hatasını taklit eder (`http_status` taşır)."""

    http_status = 429


class ServerError(Exception):
    http_status = 500


class FakeClient:
    """`embed(texts, model=, input_type=)` çağrılarını kaydeder.

    `failures`: her çağrıda sırayla fırlatılacak istisnalar (biterse başarılı döner).
    """

    def __init__(self, failures=(), dimension=3):
        self.calls = []
        self.failures = list(failures)
        self.dimension = dimension

    def embed(self, texts, model, input_type):
        self.calls.append(
            {"texts": list(texts), "model": model, "input_type": input_type}
        )
        if self.failures:
            raise self.failures.pop(0)
        vectors = [
            [float(len(text) + 1), 2.0, float(self.dimension)][: self.dimension]
            + [1.0] * max(0, self.dimension - 3)
            for text in texts
        ]
        return SimpleNamespace(embeddings=vectors, total_tokens=len(texts) * 10)


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Gerçek beklemeyi kapatır; istenen bekleme süreleri listede toplanır."""
    waited = []
    monkeypatch.setattr(embed, "sleep", waited.append)
    return waited


def norm(vector):
    return math.sqrt(sum(x * x for x in vector))


def test_modul_var():
    assert importlib.util.find_spec("backend.rag.embed") is not None


def test_belgeler_document_input_type_ile_gomulur():
    client = FakeClient()

    embed_documents(["a", "bb"], client=client, model=MODEL)

    assert len(client.calls) == 1
    assert client.calls[0]["input_type"] == "document"
    assert client.calls[0]["model"] == MODEL
    assert client.calls[0]["texts"] == ["a", "bb"]


def test_soru_query_input_type_ile_gomulur():
    client = FakeClient()

    vector = embed_query("pist kapandı mı?", client=client, model=MODEL)

    assert len(client.calls) == 1
    assert client.calls[0]["input_type"] == "query"
    assert client.calls[0]["texts"] == ["pist kapandı mı?"]
    assert len(vector) == 3


def test_vektorler_birim_uzunlukta():
    client = FakeClient()

    result = embed_documents(["a", "bbbb", "cc"], client=client, model=MODEL)

    assert len(result.vectors) == 3
    assert all(norm(v) == pytest.approx(1.0) for v in result.vectors)
    assert norm(embed_query("x", client=client, model=MODEL)) == pytest.approx(1.0)


def test_sonuc_sirayi_girdiyle_ayni():
    client = FakeClient()

    result = embed_documents(["a", "bbbb"], client=client, model=MODEL)

    # İlk bileşen metin uzunluğuna bağlı; normalleştirmeden sonra bile oranı korunur.
    assert result.vectors[0][0] != result.vectors[1][0]
    assert result.vectors[0][0] / result.vectors[0][1] == pytest.approx(1.0)
    assert result.vectors[1][0] / result.vectors[1][1] == pytest.approx(2.5)


def test_gruplar_en_cok_128_metin():
    client = FakeClient()
    texts = [f"metin {i}" for i in range(BATCH_SIZE * 2 + 5)]

    result = embed_documents(texts, client=client, model=MODEL)

    assert BATCH_SIZE == 128
    assert [len(c["texts"]) for c in client.calls] == [128, 128, 5]
    assert [t for c in client.calls for t in c["texts"]] == texts
    assert len(result.vectors) == len(texts)


def test_tam_128_metin_tek_istek():
    client = FakeClient()

    embed_documents(["m"] * 128, client=client, model=MODEL)

    assert len(client.calls) == 1


def test_bos_liste_istek_atmaz():
    client = FakeClient()

    result = embed_documents([], client=client, model=MODEL)

    assert client.calls == []
    assert result.vectors == []


def test_toplam_token_gruplarin_toplamidir():
    client = FakeClient()

    result = embed_documents(["m"] * 130, client=client, model=MODEL)

    assert result.total_tokens == 1300
    assert result.model == MODEL


def test_429da_bekleyip_yeniden_dener(sleeps):
    client = FakeClient(failures=[RateLimit(), RateLimit()])

    result = embed_documents(["a"], client=client, model=MODEL)

    assert len(client.calls) == 3
    assert len(result.vectors) == 1
    assert len(sleeps) == 2
    assert all(s > 0 for s in sleeps)


def test_bekleme_sureleri_artar(sleeps):
    client = FakeClient(failures=[RateLimit()] * 4)

    embed_documents(["a"], client=client, model=MODEL)

    assert sleeps == sorted(sleeps)
    assert len(set(sleeps)) == len(sleeps)


def test_en_cok_5_deneme_sonra_hata(sleeps):
    client = FakeClient(failures=[RateLimit()] * 10)

    with pytest.raises(EmbedError):
        embed_documents(["a"], client=client, model=MODEL)

    assert MAX_ATTEMPTS == 5
    assert len(client.calls) == 5
    # Son denemeden sonra bekleme yok.
    assert len(sleeps) == 4


def test_deneme_siniri_grup_basinadir(sleeps):
    # İlk grup 4 kez 429 alıp 5. denemede geçer; ikinci grubun sayacı sıfırdan başlar.
    client = FakeClient(failures=[RateLimit()] * 4)

    embed_documents(["m"] * 129, client=client, model=MODEL)

    assert len(client.calls) == 6


def test_429_disindaki_hata_yeniden_denenmez(sleeps):
    client = FakeClient(failures=[ServerError("sır: anahtar-123")])

    with pytest.raises(EmbedError) as info:
        embed_documents(["a"], client=client, model=MODEL)

    assert len(client.calls) == 1
    assert sleeps == []
    assert "anahtar-123" not in str(info.value)


def test_ortada_basarisiz_grup_kismi_sonuc_dondurmez():
    client = FakeClient()
    ok = client.embed

    def flaky(texts, model, input_type):
        if len(client.calls) == 1:
            client.calls.append({})
            raise ServerError()
        return ok(texts, model, input_type)

    client.embed = flaky

    with pytest.raises(EmbedError):
        embed_documents(["m"] * 200, client=client, model=MODEL)


def test_yanit_sayisi_uyusmazsa_hata():
    class Eksik(FakeClient):
        def embed(self, texts, model, input_type):
            return SimpleNamespace(embeddings=[[1.0, 0.0]], total_tokens=1)

    with pytest.raises(EmbedError):
        embed_documents(["a", "b"], client=Eksik(), model=MODEL)


def test_sifir_vektor_hata():
    class Sifir(FakeClient):
        def embed(self, texts, model, input_type):
            return SimpleNamespace(embeddings=[[0.0, 0.0]] * len(texts), total_tokens=0)

    with pytest.raises(EmbedError):
        embed_documents(["a"], client=Sifir(), model=MODEL)


def test_gruplar_arasi_boyut_tutarsizsa_hata():
    class Tutarsiz(FakeClient):
        def embed(self, texts, model, input_type):
            size = 2 + len(self.calls)
            self.calls.append({})
            return SimpleNamespace(
                embeddings=[[1.0] * size for _ in texts], total_tokens=0
            )

    with pytest.raises(EmbedError):
        embed_documents(["m"] * 129, client=Tutarsiz(), model=MODEL)


def test_bos_soru_reddedilir():
    client = FakeClient()

    with pytest.raises(ValueError):
        embed_query("   ", client=client, model=MODEL)

    assert client.calls == []


@pytest.fixture
def no_env_file(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_EMBED_MODEL", raising=False)


def test_model_adi_ortamdan_okunur(monkeypatch, no_env_file):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "  ortam-modeli ")
    client = FakeClient()

    result = embed_documents(["a"], client=client)

    assert client.calls[0]["model"] == "ortam-modeli"
    assert result.model == "ortam-modeli"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_model_adi_eksikse_turkce_config_hatasi(monkeypatch, no_env_file, value):
    if value is not None:
        monkeypatch.setenv("COPILOT_EMBED_MODEL", value)

    with pytest.raises(EmbedConfigError, match="COPILOT_EMBED_MODEL"):
        embed_documents(["a"], client=FakeClient())


def test_istemci_verilmezse_anahtar_gerekir(monkeypatch, no_env_file):
    with pytest.raises(EmbedConfigError, match="VOYAGE_API_KEY"):
        embed_documents(["a"], model=MODEL)


def test_anahtar_hata_mesajina_sizmaz(monkeypatch, no_env_file):
    monkeypatch.setenv("VOYAGE_API_KEY", "gizli-anahtar-xyz")
    monkeypatch.setattr(
        embed, "_make_client", lambda key: FakeClient(failures=[ServerError()])
    )

    with pytest.raises(EmbedError) as info:
        embed_documents(["a"], model=MODEL)

    assert "gizli-anahtar-xyz" not in str(info.value)


def test_istemci_anahtarla_olusturulur(monkeypatch, no_env_file):
    monkeypatch.setenv("VOYAGE_API_KEY", " k-1 ")
    keys = []

    def make(key):
        keys.append(key)
        return FakeClient()

    monkeypatch.setattr(embed, "_make_client", make)

    embed_documents(["a"], model=MODEL)

    assert keys == ["k-1"]


def test_koda_model_adi_gomulmemis():
    from pathlib import Path

    source = Path(embed.__file__).read_text(encoding="utf-8")

    assert "voyage-" not in source
