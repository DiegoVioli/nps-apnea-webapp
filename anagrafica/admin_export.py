import datetime
from decimal import Decimal
from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


def _formatta_valore(valore):
    """Converte date, booleani, Decimal e oggetti Django in valori compatibili con Excel."""
    if valore is None:
        return ""
    if isinstance(valore, bool):
        return "Sì" if valore else "No"
    if isinstance(valore, datetime.datetime):
        if timezone.is_aware(valore):
            valore = timezone.localtime(valore)
        return valore.strftime("%d/%m/%Y %H:%M")
    if isinstance(valore, datetime.date):
        return valore.strftime("%d/%m/%Y")
    if isinstance(valore, Decimal):
        return float(valore)
    return str(valore)


@admin.action(description="Esporta selezionati in Excel (.xlsx)")
def esporta_in_excel(modeladmin, request, queryset):
    wb = Workbook()
    ws = wb.active
    nome_modello = modeladmin.model._meta.verbose_name_plural.capitalize()
    ws.title = nome_modello[:31]  # Excel limita i nomi dei fogli a 31 caratteri

    # Esclude la checkbox di selezione 'action_checkbox'
    campi = [c for c in modeladmin.get_list_display(request) if c != "action_checkbox"]

    # 1. Intestazioni (Header)
    intestazioni = []
    for campo in campi:
        if hasattr(modeladmin.model, campo):
            field_obj = getattr(modeladmin.model, campo)
            # Se è un campo del modello, usa verbose_name
            try:
                verbose = modeladmin.model._meta.get_field(campo).verbose_name
                intestazioni.append(str(verbose).capitalize())
            except Exception:
                desc = getattr(field_obj, "short_description", campo.replace("_", " ").capitalize())
                intestazioni.append(str(desc).capitalize())
        elif hasattr(modeladmin, campo):
            metodo = getattr(modeladmin, campo)
            desc = getattr(metodo, "short_description", campo.replace("_", " ").capitalize())
            intestazioni.append(str(desc).capitalize())
        else:
            intestazioni.append(campo.replace("_", " ").capitalize())

    ws.append(intestazioni)

    # Stile intestazione
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill

    # 2. Righe dati
    for obj in queryset:
        riga = []
        for campo in campi:
            valore = None
            if hasattr(obj, f"get_{campo}_display"):
                # Gestisce automaticamente i campi con choices (es. stato, disciplina)
                valore = getattr(obj, f"get_{campo}_display")()
            elif hasattr(obj, campo):
                attr = getattr(obj, campo)
                valore = attr() if callable(attr) else attr
            elif hasattr(modeladmin, campo):
                metodo = getattr(modeladmin, campo)
                valore = metodo(obj)
            riga.append(_formatta_valore(valore))
        ws.append(riga)

    # 3. Adattamento automatico larghezza colonne
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            val_len = len(str(cell.value or ""))
            if val_len > max_len:
                max_len = val_len
        ws.column_dimensions[col_letter].width = min(max_len + 4, 50)

    # 4. Risposta HTTP con download diretto
    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M")
    filename = f"{modeladmin.model._meta.model_name}_{timestamp}.xlsx"

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response