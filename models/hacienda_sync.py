import re

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

HACIENDA_TAXPAYER_URL = "https://api.hacienda.go.cr/fe/ae"


def _clean_identification(vat):
    return re.sub(r"\D", "", vat or "")


def _query_taxpayer(vat):
    identification = _clean_identification(vat)
    if not 9 <= len(identification) <= 12:
        raise UserError(_("La identificación debe contener entre 9 y 12 dígitos."))
    try:
        response = requests.get(
            HACIENDA_TAXPAYER_URL,
            params={"identificacion": identification},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as error:
        raise UserError(_("Hacienda no respondió dentro del tiempo esperado.")) from error
    except (requests.RequestException, ValueError) as error:
        if getattr(getattr(error, "response", None), "status_code", None) == 429:
            raise UserError(
                _("Hacienda limitó temporalmente las consultas. Intente más tarde.")
            ) from error
        raise UserError(_("No fue posible consultar la API de Hacienda.")) from error
    if not isinstance(payload, dict) or not payload.get("nombre"):
        raise UserError(_("Hacienda no devolvió información para esta identificación."))
    return payload


def _sync_activities(record, payload):
    Activity = record.env["economic.activity"].sudo().with_context(active_test=False)
    records = Activity.browse()
    for item in payload.get("actividades") or []:
        if str(item.get("estado", "")).upper() != "A":
            continue
        code = str(item.get("codigo") or "").strip()
        if not code:
            continue
        old_values = item.get("ciiu3") or []
        old_code = (
            str(old_values[0].get("codigo") or "").strip()
            if old_values and isinstance(old_values[0], dict)
            else ""
        )
        activity = Activity.search([("code", "=", code)], limit=1)
        values = {
            "name": item.get("descripcion") or item.get("nombre") or code,
            "description": item.get("descripcion") or item.get("nombre") or code,
            "active": True,
        }
        if old_code:
            values["code_old"] = old_code
        if activity:
            activity.write(values)
        else:
            values["code"] = code
            activity = Activity.create(values)
        records |= activity
    return records


def _is_registered(payload):
    situation = payload.get("situacion") or {}
    status = situation.get("estado") if isinstance(situation, dict) else situation
    return str(status or "").strip().casefold().startswith("inscrito")


def _partner_tax_values(record, payload, activities):
    values = {
        "name": payload.get("nombre") or record.name,
        "inscribed": _is_registered(payload),
        "economic_activities_ids": [(6, 0, activities.ids)],
        "activity_id": activities[:1].id if activities else False,
    }
    code = str(payload.get("tipoIdentificacion") or "")
    identification = (
        record.env["identification.type"].search([("code", "=", code)], limit=1)
        if code
        else False
    )
    if identification:
        values["identification_id"] = identification.id
    return values


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == "form":
            for node in arch.xpath(
                "//field[@name='vat'][@default_focus='1']"
            ):
                node.attrib.pop("widget", None)
        return arch, view

    @api.onchange("vat", "identification_id")
    def onchange_vat(self):
        """Autofill the public tax data when a complete identification is entered."""
        for partner in self:
            identification = _clean_identification(partner.vat)
            if not 9 <= len(identification) <= 12:
                continue
            try:
                payload = _query_taxpayer(identification)
                activities = _sync_activities(partner, payload)
                partner.update(_partner_tax_values(partner, payload, activities))
            except UserError as error:
                return {
                    "warning": {
                        "title": _("Consulta de Hacienda"),
                        "message": str(error),
                        "type": "notification",
                    }
                }
        return None

    def action_get_economic_activities(self):
        for partner in self:
            payload = _query_taxpayer(partner.vat)
            activities = _sync_activities(partner, payload)
            partner.write(_partner_tax_values(partner, payload, activities))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Datos del cliente actualizados"),
                "message": _(
                    "Se cargaron el nombre, el tipo de identificación y las actividades desde Hacienda."
                ),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }


class ResCompany(models.Model):
    _inherit = "res.company"

    def action_get_economic_activities(self):
        self.ensure_one()
        payload = _query_taxpayer(self.vat)
        activities = _sync_activities(self, payload)
        partner_values = _partner_tax_values(self.partner_id, payload, activities)
        legal_name = partner_values["name"] or self.legal_name or self.name
        company_values = {
            "name": legal_name,
            "legal_name": legal_name,
            "activity_id": partner_values["activity_id"],
        }
        if partner_values.get("identification_id"):
            company_values["identification_id"] = partner_values["identification_id"]
        self.write(company_values)
        self.partner_id.write(partner_values)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Datos fiscales actualizados"),
                "message": _(
                    "Se cargaron la razón social, el tipo de identificación y %s actividades desde Hacienda."
                )
                % len(activities),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
