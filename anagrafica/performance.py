from math import ceil

from .models import Gara


METRICHE_PER_DISCIPLINA = {
    "DYN": (("distanza_m", "Distanza", "m"), ("tempo", "Tempo", "s")),
    "DNF": (("distanza_m", "Distanza", "m"), ("tempo", "Tempo", "s")),
    "STA": (("tempo", "Tempo", "s"),),
    "CWT": (("profondita_m", "Profondità", "m"), ("tempo", "Tempo", "s")),
    "CNF": (("profondita_m", "Profondità", "m"), ("tempo", "Tempo", "s")),
    "FIM": (("profondita_m", "Profondità", "m"), ("tempo", "Tempo", "s")),
}


def formatta_valore(valore, unita):
    if valore is None:
        return "Non inserito"
    if unita == "s":
        secondi = (
            int(valore.total_seconds())
            if hasattr(valore, "total_seconds")
            else int(round(float(valore)))
        )
        segno = "-" if secondi < 0 else ""
        ore, resto = divmod(abs(secondi), 3600)
        minuti, secondi = divmod(resto, 60)
        return f"{segno}{ore:02}:{minuti:02}:{secondi:02}"
    testo = format(valore, "f")
    if "." in testo:
        testo = testo.rstrip("0").rstrip(".")
    return testo


def _valore_numerico(valore, unita):
    if unita == "s" and hasattr(valore, "total_seconds"):
        return valore.total_seconds()
    return float(valore)


def prepara_storico_gare(iscrizioni):
    confronti_per_gara = []
    punti_per_metrica = {}
    etichette = dict(Gara.DISCIPLINE_CHOICES)

    for iscrizione in iscrizioni:
        dichiarazioni = {
            dichiarazione.disciplina: dichiarazione
            for dichiarazione in iscrizione.dichiarazioni.all()
        }
        risultati = {
            risultato.disciplina: risultato
            for risultato in iscrizione.risultati.all()
        }
        righe = []
        for codice, dichiarazione in dichiarazioni.items():
            risultato = risultati.get(codice)
            metriche = []
            for nome_campo, etichetta, unita in METRICHE_PER_DISCIPLINA[codice]:
                dichiarato = getattr(dichiarazione, nome_campo)
                realizzato = getattr(risultato, nome_campo) if risultato else None
                metriche.append(
                    {
                        "etichetta": etichetta,
                        "unita": unita,
                        "dichiarato": formatta_valore(dichiarato, unita),
                        "realizzato": formatta_valore(realizzato, unita),
                    }
                )
                if dichiarato is not None and realizzato is not None:
                    chiave = (codice, nome_campo)
                    punti_per_metrica.setdefault(
                        chiave,
                        {
                            "disciplina": etichette[codice],
                            "metrica": etichetta,
                            "unita": unita,
                            "punti": [],
                        },
                    )["punti"].append(
                        {
                            "data": iscrizione.gara.data_gara,
                            "gara": iscrizione.gara.nome,
                            "dichiarato": dichiarato,
                            "realizzato": realizzato,
                        }
                    )
            righe.append(
                {
                    "disciplina": etichette[codice],
                    "metriche": metriche,
                }
            )
        confronti_per_gara.append(
            {
                "iscrizione": iscrizione,
                "confronti": righe,
            }
        )

    return confronti_per_gara, [
        _crea_grafico(metrica)
        for metrica in punti_per_metrica.values()
    ]


def _crea_grafico(metrica):
    punti = sorted(metrica["punti"], key=lambda punto: punto["data"])
    valori = [
        _valore_numerico(valore, metrica["unita"])
        for punto in punti
        for valore in (punto["dichiarato"], punto["realizzato"])
    ]
    minimo = min(valori)
    massimo = max(valori)
    if minimo == massimo:
        margine = max(abs(minimo) * 0.1, 1)
    else:
        margine = (massimo - minimo) * 0.1
    minimo -= margine
    massimo += margine

    larghezza = 640
    altezza = 260
    sinistra = 58
    destra = 18
    alto = 18
    basso = 44
    ampiezza_grafico = larghezza - sinistra - destra
    altezza_grafico = altezza - alto - basso

    def coord_y(valore):
        return round(
            alto
            + (massimo - _valore_numerico(valore, metrica["unita"]))
            / (massimo - minimo)
            * altezza_grafico,
            1,
        )

    dichiarati = []
    realizzati = []
    date = []
    for indice, punto in enumerate(punti):
        x = (
            round(sinistra + indice * ampiezza_grafico / (len(punti) - 1), 1)
            if len(punti) > 1
            else round(sinistra + ampiezza_grafico / 2, 1)
        )
        label_data = punto["data"].strftime("%d/%m/%y")
        dichiarati.append(
            {
                "x": x,
                "y": coord_y(punto["dichiarato"]),
                "titolo": (
                    f"{label_data} — {punto['gara']}: dichiarato "
                    f"{formatta_valore(punto['dichiarato'], metrica['unita'])}"
                ),
            }
        )
        realizzati.append(
            {
                "x": x,
                "y": coord_y(punto["realizzato"]),
                "titolo": (
                    f"{label_data} — {punto['gara']}: realizzato "
                    f"{formatta_valore(punto['realizzato'], metrica['unita'])}"
                ),
            }
        )
        date.append({"x": x, "label": label_data})

    intervallo_tick = (massimo - minimo) / 2
    tick_valori = (minimo, minimo + intervallo_tick, massimo)
    tick = [
        {
            "y": coord_y(valore),
            "label": formatta_valore(valore, metrica["unita"]),
        }
        for valore in tick_valori
    ]
    passo_date = max(1, ceil((len(date) - 1) / 4))
    date_visibili = [
        data
        for indice, data in enumerate(date)
        if indice % passo_date == 0 or indice == len(date) - 1
    ]

    return {
        "titolo": f"{metrica['disciplina']} — {metrica['metrica']} ({metrica['unita']})",
        "date": date_visibili,
        "tick": tick,
        "dichiarati": dichiarati,
        "realizzati": realizzati,
        "linea_dichiarati": " ".join(
            f"{punto['x']},{punto['y']}" for punto in dichiarati
        ),
        "linea_realizzati": " ".join(
            f"{punto['x']},{punto['y']}" for punto in realizzati
        ),
    }
