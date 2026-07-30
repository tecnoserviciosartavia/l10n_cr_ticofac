# -*- coding: utf-8 -*-
"""Persist and explain Hacienda rejection reasons for Accounting and POS."""

import base64
import logging
import re

from lxml import etree
from markupsafe import Markup, escape

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    hacienda_rejection_reason = fields.Text(
        string="Detalle técnico del rechazo de Hacienda",
        copy=False,
        readonly=True,
    )
    hacienda_rejection_summary = fields.Text(
        string="Resumen del rechazo de Hacienda",
        compute="_compute_hacienda_rejection_summary",
        readonly=True,
    )

    @api.depends("ref", "move_type", "partner_id", "invoice_date", "tax_totals")
    def _compute_duplicated_ref_ids(self):
        """Rejected electronic invoices are not valid duplicate candidates."""
        super()._compute_duplicated_ref_ids()
        for move in self:
            move.duplicated_ref_ids = move.duplicated_ref_ids.filtered(
                lambda duplicate: duplicate.state_tributacion != "rechazado"
            )

    @api.depends("hacienda_rejection_reason")
    def _compute_hacienda_rejection_summary(self):
        for move in self:
            move.hacienda_rejection_summary = move._ticofac_humanize_rejection_reason(
                move.hacienda_rejection_reason
            )

    def _ticofac_humanize_rejection_reason(self, reason):
        """Translate common Hacienda/schema errors into an actionable explanation."""
        if not reason:
            return False

        if "OtroTexto" in reason and "OtroContenido" in reason:
            return _(
                "Los datos adicionales del documento están en un orden incorrecto dentro del XML. "
                "El número de orden de compra es válido; vuelva a generar y enviar el comprobante con la estructura corregida."
            )

        location_fields = {
            "Provincia": _("provincia"),
            "Canton": _("cantón"),
            "Distrito": _("distrito"),
            "Barrio": _("barrio"),
        }
        for technical_name, friendly_name in location_fields.items():
            if technical_name.lower() in reason.lower() and re.search(
                r"(?:False|pattern-valid|no es v[aá]lid|inv[aá]lid)", reason, re.I
            ):
                return _(
                    "La dirección está incompleta o tiene un dato inválido en el campo «%(field)s». "
                    "Abra el cliente, corrija su %(field)s y vuelva a generar el documento."
                ) % {"field": friendly_name}

        duplicate = re.search(
            r"numeraci[oó]n consecutiva\s+([0-9]+).*?ya existe", reason, re.I
        )
        if duplicate:
            return _(
                "El consecutivo %(number)s ya fue utilizado anteriormente. "
                "Genere nuevamente el documento con un consecutivo nuevo y vuelva a enviarlo."
            ) % {"number": duplicate.group(1)}

        invalid_content = re.search(
            r"Invalid content was found starting with element\s+"
            r"['\"]?\{[^}]+\}[:]?([^'\"}]+)['\"]?.*?"
            r"One of\s+['\"]?\{[^}]+\}[:]?([^'\"}]+)['\"]?\s+is expected",
            reason,
            re.I,
        )
        if invalid_content:
            received = invalid_content.group(1).strip(" '\".:[]")
            expected = invalid_content.group(2).strip(" '\".:[]")
            if received == "OtroTexto" and expected == "OtroContenido":
                return _(
                    "La sección «Otros» del XML está incompleta: se envió «OtroTexto», "
                    "pero Hacienda exige «OtroContenido». Revise los otros cargos o textos "
                    "adicionales del documento antes de reenviarlo."
                )
            return _(
                "La estructura del XML no es válida: se envió el campo «%(received)s» "
                "donde Hacienda esperaba «%(expected)s». Corrija esa sección y vuelva a enviar."
            ) % {"received": received, "expected": expected}

        missing = re.search(
            r"(?:Missing child element\(s\).*?Expected is|content of element\s+"
            r"['\"]([^'\"]+)['\"]\s+is not complete.*?expected)\s*"
            r"(?:\(|is)?\s*['\"]?(?:\{[^}]+\}:?)?([A-Za-z0-9_]+)",
            reason,
            re.I,
        )
        if missing:
            expected = missing.group(2)
            return _(
                "Falta el campo obligatorio «%s» en el comprobante. "
                "Complete ese dato y vuelva a generar el documento."
            ) % expected

        if re.search(r"(?:NumeroConsecutivo|n[uú]mero consecutivo|consecutivo).*?(?:formato|posiciones|inv[aá]lid|solo permite|no cumple)", reason, re.I):
            return _(
                "El número consecutivo del comprobante tiene un formato inválido. "
                "Revise la configuración de sucursal, terminal y consecutivos antes de reenviar."
            )

        if re.search(r"(?:CodigoActividad|actividad econ[oó]mica).*?(?:inv[aá]lid|no existe|no inscrit|RUT|rechaz)", reason, re.I):
            return _(
                "La actividad económica usada en el comprobante no es válida para el emisor. "
                "Seleccione una actividad inscrita en Hacienda y vuelva a generar el documento."
            )

        cabys = re.search(r"(?:CAByS|cabys).*?(?:inv[aá]lid|no existe|falt|requer)", reason, re.I)
        if cabys:
            return _(
                "Hay un problema con el código CAByS de uno o más productos. "
                "Verifique que todos tengan un CAByS válido y vuelva a enviar."
            )

        if re.search(r"identificaci[oó]n.*(?:receptor|cliente)|c[eé]dula.*(?:receptor|cliente)", reason, re.I):
            return _(
                "Los datos de identificación del cliente no son válidos o están incompletos. "
                "Revise el tipo y número de identificación del receptor."
            )

        if re.search(r"(?:monto|total).*?(?:no coincide|diferencia|inv[aá]lid|cálculo|calculo)", reason, re.I):
            return _(
                "Los totales del comprobante no coinciden con el detalle de líneas e impuestos. "
                "Revise cantidades, precios, descuentos e impuestos antes de reenviar."
            )

        if re.search(r"(?:CodigoMoneda|c[oó]digo de moneda|TipoCambio|tipo de cambio).*?(?:inv[aá]lid|falt|requer|no coincide)", reason, re.I):
            return _(
                "La moneda o el tipo de cambio del comprobante es inválido o está incompleto. "
                "Revise la moneda y el tipo de cambio usado en la factura."
            )

        if re.search(r"(?:firma|Signature|certificado).*?(?:inv[aá]lid|falt|vencid|error)", reason, re.I):
            return _(
                "Hacienda no pudo validar la firma electrónica. "
                "Revise el certificado, su vigencia y la configuración de firma antes de reenviar."
            )

        # Remove the generic test-environment preamble and keep the actual error concise.
        cleaned = re.sub(
            r"^Este comprobante fue recibido en el ambiente de pruebas.*?"
            r"El comprobante electr[oó]nico tiene los siguientes errores:\s*",
            "",
            reason,
            flags=re.I,
        ).strip(" []")
        if len(cleaned) > 420:
            cleaned = cleaned[:417].rstrip() + "..."
        return _(
            "Hacienda rechazó el documento por una validación que requiere revisión. "
            "Detalle principal: %s"
        ) % (cleaned or reason)

    @api.model
    def _ticofac_parse_hacienda_rejection_reason(self, encoded_xml):
        if not encoded_xml:
            return False
        try:
            raw_xml = base64.b64decode(encoded_xml)
            root = etree.fromstring(raw_xml)
            details = root.xpath("//*[local-name()='DetalleMensaje']/text()")
            if not details:
                return False
            return re.sub(r"\s+", " ", " ".join(details)).strip()
        except (ValueError, TypeError, etree.XMLSyntaxError) as error:
            _logger.warning("Could not parse Hacienda rejection response: %s", error)
            return False

    def _ticofac_store_hacienda_rejection_reason(self, encoded_xml=False):
        for move in self.filtered(lambda record: record.state_tributacion == "rechazado"):
            response = encoded_xml
            if not response:
                attachment = self.env["ir.attachment"].sudo().search(
                    [
                        ("res_model", "=", "account.move"),
                        ("res_id", "=", move.id),
                        ("res_field", "=", "xml_respuesta_tributacion"),
                    ],
                    order="id desc",
                    limit=1,
                )
                response = attachment.datas
            reason = self._ticofac_parse_hacienda_rejection_reason(response)
            if not reason:
                continue
            if move.hacienda_rejection_reason != reason:
                move.hacienda_rejection_reason = reason
            summary = move._ticofac_humanize_rejection_reason(reason)
            existing_summary = self.env["mail.message"].sudo().search_count(
                [
                    ("model", "=", "account.move"),
                    ("res_id", "=", move.id),
                    ("subject", "=", "Resumen del rechazo de Hacienda"),
                ]
            )
            if not existing_summary:
                move.message_post(
                    subject=_("Resumen del rechazo de Hacienda"),
                    body=Markup("<strong>%s</strong><br/>%s<br/><br/><small>%s</small>")
                    % (
                        escape(_("Qué debe corregir:")),
                        escape(summary),
                        escape(_("Detalle técnico de Hacienda: %s") % reason),
                    ),
                )

    @api.model
    def ticofac_backfill_rejection_reasons(self):
        rejected = self.search(
            [
                ("state_tributacion", "=", "rechazado"),
                ("move_type", "in", ("out_invoice", "out_refund")),
            ]
        )
        rejected._ticofac_store_hacienda_rejection_reason()
        return len(rejected)

    def write(self, vals):
        result = super().write(vals)
        if vals.get("state_tributacion") == "rechazado":
            self._ticofac_store_hacienda_rejection_reason()
        return result


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    @api.model_create_multi
    def create(self, vals_list):
        attachments = super().create(vals_list)
        for attachment in attachments.filtered(
            lambda item: item.res_model == "account.move"
            and item.res_id
            and item.res_field == "xml_respuesta_tributacion"
        ):
            move = self.env["account.move"].browse(attachment.res_id).exists()
            if move.state_tributacion == "rechazado":
                move._ticofac_store_hacienda_rejection_reason(attachment.datas)
        return attachments


class PosOrder(models.Model):
    _inherit = "pos.order"

    ticofac_rejection_reason = fields.Text(
        related="account_move.hacienda_rejection_reason",
        string="Detalle técnico del rechazo de Hacienda",
        readonly=True,
    )
    ticofac_rejection_summary = fields.Text(
        related="account_move.hacienda_rejection_summary",
        string="Resumen del rechazo de Hacienda",
        readonly=True,
    )
