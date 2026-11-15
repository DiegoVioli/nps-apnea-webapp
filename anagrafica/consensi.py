from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static


TIPI_CONSENSO = (
    ("REGOLAMENTO", "regolamento", "Accetto il Regolamento della ASD"),
    ("PRIVACY", "privacy", "Accetto il modulo sul trattamento dei dati personali"),
    ("FOTO_VIDEO", "foto_video", "Accetto il modulo di consenso foto e video"),
)

FILE_DOCUMENTI_CONSENSO = {
    "regolamento": "regolamento.pdf",
    "privacy": "privacy.pdf",
    "foto_video": "foto_video.pdf",
}


def url_documento_consenso(chiave, documento=None):
    if documento is None:
        documento = getattr(settings, "DOCUMENTI_CONSENSO", {}).get(chiave, {})
    if documento.get("url"):
        return documento["url"]

    percorso_statico = (
        f"anagrafica/documenti_consenso/{FILE_DOCUMENTI_CONSENSO[chiave]}"
    )
    if finders.find(percorso_statico):
        return static(percorso_statico)
    return ""


def documenti_consenso_configurati():
    documenti = getattr(settings, "DOCUMENTI_CONSENSO", {})
    return all(
        documenti.get(chiave, {}).get("versione")
        and documenti[chiave]["versione"]
        not in {"DA_CONFIGURARE", "PROVVISORIA"}
        and url_documento_consenso(chiave, documenti.get(chiave, {}))
        for _, chiave, _ in TIPI_CONSENSO
    )


def versioni_consenso_attuali():
    documenti = getattr(settings, "DOCUMENTI_CONSENSO", {})
    return {
        tipo: documenti.get(chiave, {}).get("versione", "PROVVISORIA")
        for tipo, chiave, _ in TIPI_CONSENSO
    }


def consensi_mancanti(socio):
    from .models import ConsensoSocio

    attuali = versioni_consenso_attuali()
    registrati = {}
    for tipo, versione in (
        socio.consensi.order_by("-accettato_il").values_list("tipo", "versione_modulo")
    ):
        registrati.setdefault(tipo, versione)
    return [
        tipo
        for tipo, versione in attuali.items()
        if registrati.get(tipo) != versione
    ]
