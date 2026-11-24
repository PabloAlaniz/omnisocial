from __future__ import annotations

from dataclasses import replace

import pytest
from typing_extensions import override

from omnisocial.adapters.http.transport import TransportError
from omnisocial.adapters.stores.memory import InMemoryPublicationRepository
from omnisocial.application.results import AuthorizationStarted, Connected, Done, Refusal, Refused
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import (
    ErrorKind,
    PermissionMissing,
    ProviderError,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import (
    Draft,
    DraftIssue,
    Media,
    MediaKind,
    Outcome,
    Publication,
    PublicationStatus,
)
from tests import fakes
from tests.application.conftest import World, build_world
from tests.fakes import FAKE, NOW, FakeOptions

DRAFT = Draft("hola", first_comment="primero", options=FakeOptions())


async def _assets(world: World) -> dict[str, str]:
    started = await world.social.start_authorization.execute("falsa", purpose=Purpose.CONNECT, owner="c")
    assert isinstance(started, AuthorizationStarted)
    result = await world.social.complete_authorization.execute(state=started.state, code="abc")
    assert isinstance(result, Connected)
    return {asset.kind: asset.id for asset in result.assets}


async def _page(world: World) -> str:
    return (await _assets(world))["pagina"]


async def _publish(world: World, page: str, **kwargs: str) -> Publication:
    result = await world.social.publish.execute(page, DRAFT, **kwargs)
    assert isinstance(result, Done)
    return result.value


async def test_publicar_guarda_lo_que_salio(world: World) -> None:
    page = await _page(world)
    publication = await _publish(world, page)
    assert (publication.status, publication.post_id, publication.url) == (
        PublicationStatus.PUBLISHED,
        "post-1",
        "https://red/1",
    )
    assert (publication.asset_id, publication.owner, publication.provider) == (page, "c", FAKE)
    assert world.network.publisher.published == [DRAFT]
    checked = await world.social.check_publication.execute(publication.id)
    assert checked == Done(publication)


async def test_un_borrador_que_no_entra_no_llega_a_la_red(world: World) -> None:
    page = await _page(world)
    draft = Draft("x" * 51, media=(Media(MediaKind.IMAGE, "http://inseguro/a.jpg"),))
    refused = await world.social.publish.execute(page, draft)
    assert isinstance(refused, Refused)
    assert refused.reason is Refusal.INVALID_DRAFT
    assert [p.issue for p in refused.problems] == [DraftIssue.TEXT_TOO_LONG, DraftIssue.MEDIA_URL_INVALID]
    assert "máximo es 50" in (refused.detail or "")
    assert world.network.publisher.published == []
    validated = await world.social.validate_draft.execute(page, draft)
    assert isinstance(validated, Done)
    assert validated.value == refused.problems
    assert await world.social.validate_draft.execute(page, DRAFT) == Done(())


async def test_con_la_misma_clave_no_se_publica_dos_veces(world: World) -> None:
    page = await _page(world)
    first = await _publish(world, page, idempotency_key="k1")
    again = await _publish(world, page, idempotency_key="k1")
    other = await _publish(world, page, idempotency_key="k2")
    assert again == first
    assert other.id != first.id
    assert len(world.network.publisher.published) == 2
    # Sin clave, cada pedido es una publicación nueva.
    await _publish(world, page)
    await _publish(world, page)
    assert len(world.network.publisher.published) == 4


async def test_en_etapas_se_retoma_hasta_que_sale(world: World) -> None:
    page = await _page(world)
    world.network.publisher.pending = True
    pending = await _publish(world, page, idempotency_key="k1")
    assert (pending.status, pending.resume, pending.post_id) == (
        PublicationStatus.PENDING,
        {"paso": "1"},
        None,
    )
    # Repetir el pedido devuelve la que está en curso, sin publicar de nuevo.
    assert await _publish(world, page, idempotency_key="k1") == pending

    world.network.publisher.outcome = Outcome(PublicationStatus.PENDING, resume={"paso": "2"})
    still = await world.social.check_publication.execute(pending.id)
    assert isinstance(still, Done)
    assert (still.value.status, still.value.resume) == (PublicationStatus.PENDING, {"paso": "2"})

    world.network.publisher.outcome = None
    done = await world.social.check_publication.execute(pending.id)
    assert isinstance(done, Done)
    assert (done.value.status, done.value.post_id) == (PublicationStatus.PUBLISHED, "post-1")
    assert world.network.publisher.resumed == [{"paso": "1"}, {"paso": "2"}]
    # Ya salió: consultarla de nuevo no llama a la red.
    assert await world.social.check_publication.execute(pending.id) == done
    assert len(world.network.publisher.resumed) == 2
    assert len(world.network.publisher.published) == 1


async def test_publicada_con_error_no_es_un_fracaso(world: World) -> None:
    page = await _page(world)
    world.network.publisher.outcome = Outcome(
        PublicationStatus.PUBLISHED_WITH_ERROR, post_id="post-9", error="el primer comentario no salió"
    )
    publication = await _publish(world, page, idempotency_key="k1")
    assert (publication.status, publication.post_id, publication.error) == (
        PublicationStatus.PUBLISHED_WITH_ERROR,
        "post-9",
        "el primer comentario no salió",
    )
    assert publication.is_final
    assert await _publish(world, page, idempotency_key="k1") == publication
    assert len(world.network.publisher.published) == 1


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PermissionMissing(FAKE, "falta publicar"), Refusal.MISSING_PERMISSION),
        (RateLimited(FAKE, "despacio", retry_after=60.0), Refusal.RATE_LIMITED),
        (ProviderError(FAKE, "video muy largo", kind=ErrorKind.INVALID_REQUEST), Refusal.CONTENT_REJECTED),
        (TokenRejected(FAKE, "token vencido"), Refusal.CONNECTION_INVALID),
    ],
)
async def test_si_no_salio_con_certeza_se_puede_reintentar_con_la_misma_clave(
    world: World, error: Exception, reason: Refusal
) -> None:
    page = await _page(world)
    world.network.publisher.fail_with = error
    refused = await world.social.publish.execute(page, DRAFT, idempotency_key="k1")
    assert isinstance(refused, Refused)
    assert refused.reason is reason
    world.network.publisher.fail_with = None
    retried = await world.social.publish.execute(page, DRAFT, idempotency_key="k1")
    if reason is Refusal.CONNECTION_INVALID:
        assert retried == refused
    else:
        assert isinstance(retried, Done)
        assert retried.value.status is PublicationStatus.PUBLISHED


@pytest.mark.parametrize("error", [TransportError("se cortó"), ProviderError(FAKE, "se cayó", status=500)])
async def test_si_no_se_sabe_que_paso_queda_en_duda_y_no_se_repite(world: World, error: Exception) -> None:
    page = await _page(world)
    world.network.publisher.fail_with = error
    with pytest.raises(type(error)):
        await world.social.publish.execute(page, DRAFT, idempotency_key="k1")
    world.network.publisher.fail_with = None
    again = await _publish(world, page, idempotency_key="k1")
    assert again.status is PublicationStatus.STARTED
    assert world.network.publisher.published == []
    assert await world.social.check_publication.execute(again.id) == Done(again)


async def test_retomar_traduce_los_errores_de_la_red(world: World) -> None:
    page = await _page(world)
    world.network.publisher.pending = True
    pending = await _publish(world, page)
    world.network.publisher.fail_with = RateLimited(FAKE, "despacio")
    limited = await world.social.check_publication.execute(pending.id)
    assert isinstance(limited, Refused)
    assert limited.reason is Refusal.RATE_LIMITED
    world.network.publisher.fail_with = ProviderError(FAKE, "se cayó", status=500)
    with pytest.raises(ProviderError):
        await world.social.check_publication.execute(pending.id)
    # Sigue pendiente: se retoma más tarde.
    world.network.publisher.fail_with = None
    done = await world.social.check_publication.execute(pending.id)
    assert isinstance(done, Done)
    assert done.value.status is PublicationStatus.PUBLISHED
    assert await world.social.check_publication.execute("nada") == Refused(Refusal.NOT_FOUND)


async def test_retomar_con_la_conexion_caida(world: World) -> None:
    page = await _page(world)
    world.network.publisher.pending = True
    pending = await _publish(world, page)
    world.network.publisher.fail_with = TokenRejected(FAKE, "token vencido")
    rejected = await world.social.check_publication.execute(pending.id)
    assert isinstance(rejected, Refused)
    assert rejected.reason is Refusal.CONNECTION_INVALID
    again = await world.social.check_publication.execute(pending.id)
    assert isinstance(again, Refused)
    assert again.reason is Refusal.CONNECTION_INVALID


async def test_borrar_una_publicacion(world: World) -> None:
    page = await _page(world)
    assert await world.social.delete_post.execute(page, post_id="post-1") == Done(None)
    assert world.network.publisher.deleted == ["post-1"]
    world.network.publisher.fail_with = PermissionMissing(FAKE, "falta borrar")
    missing = await world.social.delete_post.execute(page, post_id="post-1")
    assert isinstance(missing, Refused)
    assert missing.reason is Refusal.MISSING_PERMISSION
    world.network.publisher.fail_with = ProviderError(FAKE, "se cayó", status=500)
    with pytest.raises(ProviderError):
        await world.social.delete_post.execute(page, post_id="post-1")


async def test_un_activo_o_una_red_que_no_publica(world: World) -> None:
    assets = await _assets(world)
    # La red no declara límites para ese tipo de activo.
    account = await world.social.publish.execute(assets["cuenta"], DRAFT)
    assert account == Refused(Refusal.NOT_SUPPORTED, capability=Capability.PUBLISHING)
    assert await world.social.publish.execute("nada", DRAFT) == Refused(Refusal.NOT_FOUND)
    assert await world.social.delete_post.execute("nada", post_id="p") == Refused(Refusal.NOT_FOUND)
    assert await world.social.validate_draft.execute("nada", DRAFT) == Refused(Refusal.NOT_FOUND)

    without = build_world(only=frozenset(Capability) - {Capability.PUBLISHING})
    page = await _page(without)
    assert await without.social.publish.execute(page, DRAFT) == Refused(
        Refusal.NOT_SUPPORTED, capability=Capability.PUBLISHING
    )


async def test_borrar_donde_la_red_no_lo_ofrece(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    page = await _page(world)
    spec = replace(fakes.FAKE_SPEC, publishing={"pagina": replace(fakes.FAKE_LIMITS, delete=False)})
    provider = world.social.registry.get("falsa")
    monkeypatch.setattr(world.social.registry, "get", lambda _id: replace(provider, spec=spec))
    refused = await world.social.delete_post.execute(page, post_id="post-1")
    assert refused == Refused(Refusal.ACTION_NOT_OFFERED, detail="delete", capability=Capability.PUBLISHING)
    assert world.network.publisher.deleted == []


async def test_dos_pedidos_a_la_vez_con_la_misma_clave() -> None:
    """El que pierde la reserva no publica: devuelve la del otro, o avisa si el otro ya la liberó."""

    class Carrera(InMemoryPublicationRepository):
        vanish = False

        @override
        async def add(self, publication: Publication) -> bool:
            if publication.idempotency_key == "k1" and not self.vanish:
                await super().add(
                    Publication(
                        "otra",
                        publication.asset_id,
                        "c",
                        FAKE,
                        PublicationStatus.STARTED,
                        NOW,
                        NOW,
                        idempotency_key="k1",
                    )
                )
            return False

    repo = Carrera()
    world = build_world(publications=repo)
    page = await _page(world)
    lost = await world.social.publish.execute(page, DRAFT, idempotency_key="k1")
    assert isinstance(lost, Done)
    assert (lost.value.id, lost.value.status) == ("otra", PublicationStatus.STARTED)
    repo.vanish = True
    gone = await world.social.publish.execute(page, DRAFT, idempotency_key="k2")
    assert isinstance(gone, Refused)
    assert gone.reason is Refusal.NOT_FOUND
    assert world.network.publisher.published == []


async def test_un_activo_guardado_antes_de_que_la_red_publicara(world: World) -> None:
    """Sus capacidades guardadas no incluyen publicar: hay que volver a sincronizar los activos."""
    page = await _page(world)
    stored = await world.assets.get(page)
    assert stored is not None
    old = replace(stored, capabilities=stored.capabilities - {Capability.PUBLISHING})
    await world.assets.replace_for_connection(stored.connection_id, [old])
    assert await world.social.publish.execute(page, DRAFT) == Refused(
        Refusal.NOT_SUPPORTED, capability=Capability.PUBLISHING
    )


async def test_dos_procesos_retoman_la_misma_publicacion() -> None:
    """El que pierde relee y devuelve lo que guardó el otro."""

    class Lenta(InMemoryPublicationRepository):
        lost = False

        @override
        async def save(self, publication: Publication, *, expected_version: int) -> bool:
            if publication.status is PublicationStatus.PUBLISHED and not self.lost:
                self.lost = True
                winner = replace(publication, post_id="del-otro")
                await super().save(winner, expected_version=expected_version)
                return False
            return await super().save(publication, expected_version=expected_version)

    world = build_world(publications=Lenta())
    page = await _page(world)
    world.network.publisher.pending = True
    pending = await _publish(world, page)
    done = await world.social.check_publication.execute(pending.id)
    assert isinstance(done, Done)
    assert done.value.post_id == "del-otro"
