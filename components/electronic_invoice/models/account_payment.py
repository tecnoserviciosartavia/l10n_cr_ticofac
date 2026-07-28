# -*- coding: utf-8 -*-
import base64
import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal

import pytz
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import api_facturae

_logger = logging.getLogger(__name__)


class PaymentMethods(models.Model):
    _name = "payment.methods"
    _description = 'Payment Methods'

    # ==============================================================================================
    #                                          PAYMENT METHODS
    # ==============================================================================================

    active = fields.Boolean(default=True)
    sequence = fields.Char(
        string="Code", help="Hacienda payment method code (01-05, 99)"
    )
    name = fields.Char(string="Name")
    notes = fields.Text(string="Notes")


class AccountPayment(models.Model):
    _inherit = "account.payment"

    # === REP Generation Flag ===
    generate_rep = fields.Boolean(
        string="Generate REP",
        default=False,
        copy=False,
        help="Check this box to generate a Recibo Electrónico de Pago upon validation.",
    )

    # Technical field to link invoice before reconciliation (for REP generation context)
    rep_bak_invoice_id = fields.Many2one(
        "account.move",
        string="REP Source Invoice",
        copy=False,
        help="Primary invoice linked to this payment for REP generation.",
    )

    # Many2many to support multi-invoice payments
    rep_all_invoice_ids = fields.Many2many(
        "account.move",
        "account_payment_rep_invoice_rel",
        "payment_id",
        "invoice_id",
        string="REP All Invoices",
        copy=False,
        help="All invoices linked to this payment for REP generation.",
    )

    # === REP Display Fields (Related to Move) ===
    rep_number_electronic = fields.Char(
        related="move_id.number_electronic", string="REP Electronic Key", readonly=True
    )
    rep_date_issuance = fields.Char(
        related="move_id.date_issuance", string="REP Issue Date", readonly=True
    )
    rep_state_tributacion = fields.Selection(
        related="move_id.state_tributacion", string="Hacienda Status", readonly=True
    )
    rep_xml_comprobante = fields.Binary(
        related="move_id.xml_comprobante", string="REP XML", readonly=True
    )
    rep_fname_xml_comprobante = fields.Char(
        related="move_id.fname_xml_comprobante",
        string="REP XML Filename",
        readonly=True,
    )
    rep_xml_respuesta_tributacion = fields.Binary(
        related="move_id.xml_respuesta_tributacion",
        string="Hacienda Response XML",
        readonly=True,
    )
    rep_fname_xml_respuesta_tributacion = fields.Char(
        related="move_id.fname_xml_respuesta_tributacion",
        string="Response XML Filename",
        readonly=True,
    )
    rep_return_message = fields.Char(
        related="move_id.electronic_invoice_return_message",
        string="Hacienda Message",
        readonly=True,
    )

    # Computed field for UI: indicates if payment has immutable REP
    rep_is_immutable = fields.Boolean(
        string="REP Immutable",
        compute="_compute_rep_is_immutable",
        help="True if payment has a REP in protected state (cannot be modified)",
    )

    # Computed field for UI: indicates if REP can be cleared (rejected state)
    rep_can_clear = fields.Boolean(
        string="REP Can Clear",
        compute="_compute_rep_can_clear",
        help="True if REP data can be cleared (rejected state only)",
    )

    def _compute_rep_is_immutable(self):
        """Compute if payment has a protected (immutable) REP."""
        for payment in self:
            has_protected, _ = payment._has_protected_rep()
            payment.rep_is_immutable = has_protected

    def _compute_rep_can_clear(self):
        """Compute if REP data can be cleared (only for rejected REPs)."""
        for payment in self:
            payment.rep_can_clear = payment._has_rejected_rep()

    # -------------------------------------------------------------------------
    # REP STATE HELPERS
    # -------------------------------------------------------------------------

    def _has_protected_rep(self):
        """
        Check if payment has a REP that should be preserved (not regenerated).

        Protected states:
        - 'procesando': REP sent, awaiting Hacienda response
        - 'aceptado': REP accepted by Hacienda
        - 'recibido': REP received by Hacienda

        Returns:
            tuple: (has_protected_rep: bool, state: str or False)
        """
        self.ensure_one()
        if not self.move_id or not self.move_id.number_electronic:
            return False, False

        protected_states = ("procesando", "aceptado", "recibido")
        state = self.move_id.state_tributacion
        return state in protected_states, state

    def _has_rejected_rep(self):
        """
        Check if payment has a rejected REP that can be auto-cleared.

        Returns:
            bool: True if REP exists and was rejected
        """
        self.ensure_one()
        if not self.move_id or not self.move_id.number_electronic:
            return False
        return self.move_id.state_tributacion == "rechazado"

    def _clear_rep_data(self):
        """
        Clear REP data from the payment's move_id.
        Used when REP was rejected and user wants to retry.
        """
        self.ensure_one()
        if not self.move_id:
            return

        self.move_id.write(
            {
                "tipo_documento": False,
                "number_electronic": False,
                "date_issuance": False,
                "sequence": False,
                "state_tributacion": False,
                "xml_comprobante": False,
                "fname_xml_comprobante": False,
                "xml_respuesta_tributacion": False,
                "fname_xml_respuesta_tributacion": False,
                "electronic_invoice_return_message": False,
            }
        )
        _logger.info(
            "REP data cleared for payment %s (move_id: %s)", self.name, self.move_id.id
        )

    # -------------------------------------------------------------------------
    # OVERRIDE: action_draft - Block reset when REP exists
    # -------------------------------------------------------------------------

    def action_draft(self):
        """
        Override to block reset to draft when payment has a protected REP.

        Behavior:
        - Protected REP (procesando/aceptado/recibido): BLOCK reset with UserError.
          The payment cannot be reverted to draft once REP is sent/accepted.
        - Rejected REP: Allow reset, auto-clear REP data so user can retry.
        - No REP: Standard behavior.
        """
        for payment in self:
            has_protected, state = payment._has_protected_rep()

            if has_protected:
                # BLOCK: Cannot reset payment with protected REP
                raise UserError(
                    _(
                        "Este pago tiene un Recibo Electrónico de Pago (REP) con estado '%s' "
                        "y no puede ser pasado a borrador.\n\n"
                        "Clave electrónica: %s\n\n"
                        "Los pagos con REP enviado o aceptado por Hacienda no pueden ser modificados."
                    )
                    % (state, payment.move_id.number_electronic)
                )

            if payment._has_rejected_rep():
                # Allow reset for rejected REP, auto-clear data for retry
                payment._clear_rep_data()
                _logger.info(
                    "Payment %s reset to draft with rejected REP. "
                    "REP data cleared for retry.",
                    payment.name,
                )

        return super(AccountPayment, self).action_draft()

    # -------------------------------------------------------------------------
    # OVERRIDE: write - Block edits when REP exists
    # -------------------------------------------------------------------------

    # Fields that affect REP XML and must be immutable once REP is generated
    REP_PROTECTED_FIELDS = {
        "amount",
        "currency_id",
        "date",
        "journal_id",
        "payment_method_line_id",
        "partner_id",
        "payment_type",
        "partner_type",
    }

    def write(self, vals):
        """
        Override to block edits to REP-impacting fields when REP exists.

        If payment has a protected REP (procesando/aceptado/recibido),
        monetary and REP-relevant fields cannot be modified.
        """
        # Check if any protected field is being modified
        protected_fields_in_vals = set(vals.keys()) & self.REP_PROTECTED_FIELDS

        if protected_fields_in_vals:
            for payment in self:
                has_protected, state = payment._has_protected_rep()
                if has_protected:
                    raise UserError(
                        _(
                            "Este pago tiene un Recibo Electrónico de Pago (REP) con estado '%s' "
                            "y no puede ser modificado.\n\n"
                            "Clave electrónica: %s\n\n"
                            "Campos protegidos: %s\n\n"
                            "Los pagos con REP enviado o aceptado por Hacienda son inmutables."
                        )
                        % (
                            state,
                            payment.move_id.number_electronic,
                            ", ".join(protected_fields_in_vals),
                        )
                    )

        return super(AccountPayment, self).write(vals)

    # -------------------------------------------------------------------------
    # ACTION: Clear REP Data (for rejected REPs)
    # -------------------------------------------------------------------------

    def action_clear_rep_data(self):
        """
        Explicit action to clear REP data for rejected REPs.
        Allows user to retry REP generation after fixing issues.
        """
        self.ensure_one()

        if not self.move_id or not self.move_id.number_electronic:
            raise UserError(_("Este pago no tiene datos de REP para limpiar."))

        has_protected, state = self._has_protected_rep()
        if has_protected:
            raise UserError(
                _(
                    "No se pueden limpiar los datos del REP porque tiene estado '%s'.\n"
                    "Solo se pueden limpiar datos de REPs rechazados."
                )
                % state
            )

        if not self._has_rejected_rep():
            raise UserError(
                _(
                    "Solo se pueden limpiar datos de REPs rechazados.\n"
                    "Estado actual: %s"
                )
                % (self.move_id.state_tributacion or "N/A")
            )

        self._clear_rep_data()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("REP Data Cleared"),
                "message": _(
                    "Los datos del REP han sido limpiados. Puede generar un nuevo REP al validar el pago."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    # -------------------------------------------------------------------------
    # OVERRIDE: action_post - Synchronous REP generation flow
    # -------------------------------------------------------------------------

    def action_post(self):
        """
        Override to implement synchronous REP generation flow.

        Flow:
        1. BEFORE posting: Validate prerequisites (blocking)
        2. Post payment (core Odoo logic - creates move_id)
        3. AFTER posting: Generate/sign REP XML and send to Hacienda

        If validation fails, raise UserError to abort payment.
        """
        # 1. Pre-posting validation (BLOCKING) - validate before posting
        payments_for_rep = self.env["account.payment"]
        for payment in self:
            if payment.generate_rep:
                # Check if REP already exists and is protected
                has_protected, state = payment._has_protected_rep()
                if has_protected:
                    raise UserError(
                        _(
                            "Este pago ya tiene un REP con estado '%s' que no puede ser regenerado.\n"
                            "Clave electrónica: %s\n\n"
                            "Si necesita generar un nuevo REP, primero debe anular el existente."
                        )
                        % (state, payment.move_id.number_electronic)
                    )

                # Validate all prerequisites - raises UserError on failure
                payment._validate_rep_prerequisites()
                payments_for_rep |= payment

        # 2. Post Payment (Core Odoo Logic) - this creates move_id
        res = super(AccountPayment, self).action_post()

        # 3. After posting: Generate XML, sign, and send to Hacienda
        for payment in payments_for_rep:
            if not payment.move_id:
                _logger.error(
                    "Payment %s has no move_id after posting. Cannot generate REP.",
                    payment.name,
                )
                continue

            try:
                # Generate and sign XML
                rep_vals = payment._generate_and_sign_rep_xml()

                # Write REP data to the journal entry
                payment.move_id.write(rep_vals)

                _logger.info(
                    "REP XML generated and signed for payment %s", payment.name
                )

                # Send to Hacienda (non-blocking - errors don't rollback payment)
                if payment.move_id.xml_comprobante:
                    payment._send_rep_to_hacienda()

            except UserError:
                # Re-raise UserError to show to user
                raise
            except Exception as e:
                _logger.exception(
                    "Error generating REP for payment %s: %s", payment.name, e
                )
                # Store error in move for visibility
                if payment.move_id:
                    payment.move_id.write(
                        {
                            "state_tributacion": "error",
                            "electronic_invoice_return_message": str(e),
                        }
                    )

        return res

    # -------------------------------------------------------------------------
    # REP PREREQUISITE VALIDATION
    # -------------------------------------------------------------------------

    def _validate_rep_prerequisites(self):
        """
        Validate all prerequisites for REP generation.
        Raises UserError if any validation fails.
        """
        self.ensure_one()
        company = self.company_id

        # === Company Configuration ===
        if company.frm_ws_ambiente == "disabled":
            raise UserError(
                _("La Facturación Electrónica está deshabilitada para esta compañía.")
            )

        if not company.signature:
            raise UserError(
                _(
                    "La llave criptográfica (certificado P12) de Factura Electrónica no está configurada."
                )
            )

        if not company.frm_pin:
            raise UserError(_("El PIN de Factura Electrónica no está configurado."))

        if not company.frm_ws_identificador or not company.frm_ws_password:
            raise UserError(
                _(
                    "Las credenciales de Hacienda (usuario/contraseña) no están configuradas."
                )
            )

        # === Invoice Validation ===
        main_invoice = self._get_rep_source_invoice()
        if not main_invoice:
            raise UserError(
                _(
                    "No se puede identificar la factura origen para la generación del REP. "
                    "Por favor asegúrese de que el pago esté vinculado a una factura electrónica válida."
                )
            )

        # Check invoice has valid electronic key
        if (
            not main_invoice.number_electronic
            or len(main_invoice.number_electronic) != 50
        ):
            raise UserError(
                _(
                    "La factura '%s' no tiene una clave electrónica válida de 50 caracteres."
                )
                % main_invoice.name
            )

        # Check invoice is accepted by Hacienda
        if main_invoice.state_tributacion != "aceptado":
            raise UserError(
                _(
                    "La factura '%s' no ha sido aceptada por Hacienda (estado: %s). "
                    "El REP solo puede generarse para facturas aceptadas."
                )
                % (main_invoice.name, main_invoice.state_tributacion or "N/A")
            )

        # === Journal Configuration ===
        if not main_invoice.journal_id.REP_sequence_id:
            raise UserError(
                _(
                    "El Diario de Ventas '%s' no tiene una secuencia de REP configurada. "
                    "Por favor configúrela en Contabilidad > Configuración > Diarios."
                )
                % main_invoice.journal_id.name
            )

        # === Sale Condition Validation ===
        allowed_conditions = [
            "02",
            "08",
        ]  # Crédito, Servicios prestados al Estado a Crédito

        invoices_to_check = self._get_all_rep_invoices()
        for inv in invoices_to_check:
            cond_code = (
                inv.invoice_payment_term_id.sale_conditions_id.code
                if inv.invoice_payment_term_id
                and inv.invoice_payment_term_id.sale_conditions_id
                else False
            )
            if cond_code not in allowed_conditions:
                raise UserError(
                    _(
                        "El REP solo puede generarse para facturas con Condición de Venta = "
                        "Crédito (02) o Servicios prestados al Estado a Crédito (08). "
                        "La factura '%s' tiene condición: %s"
                    )
                    % (inv.name, cond_code or "N/A")
                )

    def _get_rep_source_invoice(self):
        """
        Get the primary invoice for REP generation.
        This determines the journal for sequence and other metadata.
        """
        self.ensure_one()

        # First try the explicitly linked invoice
        if self.rep_bak_invoice_id:
            return self.rep_bak_invoice_id

        # Fallback to reconciled invoices (if available post-reconciliation)
        if self.reconciled_invoice_ids:
            valid = self.reconciled_invoice_ids.filtered(
                lambda m: m.state_tributacion == "aceptado" and m.number_electronic
            )
            if valid:
                return valid[0]

        return False

    def _get_all_rep_invoices(self):
        """
        Get all invoices to be referenced in the REP.
        """
        self.ensure_one()

        # Use explicit M2M if available
        if self.rep_all_invoice_ids:
            return self.rep_all_invoice_ids.filtered(
                lambda m: m.state_tributacion == "aceptado" and m.number_electronic
            )

        # Fallback to single invoice
        main = self._get_rep_source_invoice()
        return main if main else self.env["account.move"]

    # -------------------------------------------------------------------------
    # REP XML GENERATION AND SIGNING
    # -------------------------------------------------------------------------

    def _generate_and_sign_rep_xml(self):
        """
        Generate and sign the REP XML document.

        Returns dict of values to write to payment.move_id:
            - tipo_documento
            - number_electronic
            - date_issuance
            - state_tributacion
            - xml_comprobante
            - fname_xml_comprobante
            - electronic_invoice_return_message
        """
        self.ensure_one()

        invoice = self._get_rep_source_invoice()
        if not invoice:
            raise UserError(
                _(
                    "No se puede identificar la factura origen para la generación del REP."
                )
            )

        # A. Generate Sequence & Electronic Key
        doc_type = "REP"
        sequence = invoice.journal_id.REP_sequence_id.next_by_id()
        if not sequence:
            raise UserError(
                _("Error al generar la secuencia de REP desde el diario '%s'.")
                % invoice.journal_id.name
            )

        # Generate issue timestamp in Costa Rica timezone
        now_cr = datetime.datetime.now(pytz.timezone("America/Costa_Rica"))
        date_issuance = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")

        # Generate 50-character electronic key
        # IMPORTANT: Pass the current date (now_cr) so the Clave date matches FechaEmision
        # Otherwise Hacienda error -405: "La fecha de la clave númerica no concuerda con el campo Fecha Emisión"
        response = api_facturae.get_clave_hacienda(
            invoice,  # Use invoice for company/vat info
            doc_type,
            sequence,
            invoice.journal_id.sucursal,
            invoice.journal_id.terminal,
            situacion="normal",
            fecha_emision=now_cr.date(),  # Use REP emission date, not invoice date
        )

        number_electronic = response.get("clave")
        if not number_electronic or len(number_electronic) != 50:
            raise UserError(
                _("Error al generar la clave electrónica válida para el REP.")
            )

        # B. Calculate Tax Breakdown (proration for partial payments)
        lines_data, tax_breakdown, totals = self._calculate_rep_proration()

        if not lines_data:
            raise UserError(
                _(
                    "No se generaron datos de línea válidos para el REP. Asegúrese de que las facturas tengan líneas de producto con impuestos."
                )
            )

        # C. Generate XML
        try:
            xml_string_builder = api_facturae.gen_xml_rep_v44(
                payment=self,
                number_electronic=number_electronic,
                date_issuance=date_issuance,
                lines=lines_data,
                tax_breakdown=tax_breakdown,
                totals=totals,
            )
            xml_str = str(xml_string_builder)

        except Exception as e:
            _logger.exception("Error generando XML del REP")
            raise UserError(_("Error al generar el XML del REP: %s") % str(e))

        # D. Sign XML
        try:
            xml_signed = api_facturae.sign_xml(
                self.company_id.signature, self.company_id.frm_pin, xml_str
            )
        except Exception as e:
            _logger.exception("Error firmando XML del REP")
            raise UserError(_("Error al firmar el XML del REP: %s") % str(e))

        # E. Prepare return values
        xml_final = base64.b64encode(xml_signed)
        filename = f"{doc_type}_{number_electronic}.xml"

        # NOTE: state_tributacion is intentionally set to False (not 'procesando')
        # This indicates "generated but not yet sent to Hacienda".
        # The cron _send_rep_to_hacienda_cron() will pick it up and send it,
        # then set state_tributacion = 'procesando' upon successful send.
        return {
            "tipo_documento": doc_type,
            "number_electronic": number_electronic,
            "date_issuance": date_issuance,
            "sequence": response.get("consecutivo"),
            "state_tributacion": False,
            "xml_comprobante": xml_final,
            "fname_xml_comprobante": filename,
            "electronic_invoice_return_message": _(
                "Generado y Firmado - Pendiente de envío"
            ),
        }

    # -------------------------------------------------------------------------
    # SEND REP TO HACIENDA
    # -------------------------------------------------------------------------

    def _send_rep_to_hacienda(self):
        """
        Send the signed REP XML to Hacienda.

        This method is designed to be non-blocking for the payment flow.
        Errors are logged but don't raise exceptions to avoid rolling back the payment.
        """
        self.ensure_one()
        move = self.move_id
        company = self.company_id

        try:
            if not move.xml_comprobante:
                _logger.warning("REP Payment %s has no XML to send.", self.name)
                return

            # Decode signed XML
            xml_signed = base64.b64decode(move.xml_comprobante)

            # Get authentication token
            token = api_facturae.get_token_hacienda(move, company.frm_ws_ambiente)
            if not token:
                move.state_tributacion = "error"
                move.electronic_invoice_return_message = _(
                    "Error al obtener el token de autenticación de Hacienda."
                )
                _logger.error(
                    "Failed to get Hacienda token for REP %s", move.number_electronic
                )
                return

            # Send to Hacienda
            response_json = api_facturae.send_xml_fe(
                move, token, move.date_issuance, xml_signed, company.frm_ws_ambiente
            )

            status = response_json.get("status")
            text = response_json.get("text", "")

            if status in [200, 202]:
                move.state_tributacion = "procesando"
                move.electronic_invoice_return_message = _(
                    "Enviado a Hacienda - Procesando"
                )
                _logger.info(
                    "REP %s sent successfully. Status: %s",
                    move.number_electronic,
                    status,
                )
            else:
                move.state_tributacion = "error"
                move.electronic_invoice_return_message = text or _(
                    "Error al enviar a Hacienda"
                )
                _logger.error(
                    "Error sending REP %s to Hacienda. Status: %s, Text: %s",
                    move.number_electronic,
                    status,
                    text,
                )

        except Exception as e:
            _logger.exception("Exception sending REP to Hacienda: %s", e)
            move.state_tributacion = "error"
            move.electronic_invoice_return_message = str(e)

    # -------------------------------------------------------------------------
    # CHECK REP STATUS FROM HACIENDA (Manual button action)
    # -------------------------------------------------------------------------

    def action_check_rep_hacienda(self):
        """
        Manually check the REP status from Hacienda.

        This method is called by the "Check now / Consultar ahora" button
        in the payment form when REP is in 'procesando' state.

        Replicates the same behavior as invoice's action_check_hacienda_for_invoices.
        """
        self.ensure_one()
        move = self.move_id
        company = self.company_id

        # Validate prerequisites
        if not self.generate_rep:
            raise UserError(_("Este pago no tiene habilitada la generación de REP."))

        if not move:
            raise UserError(_("Este pago no tiene un asiento contable asociado."))

        if not move.number_electronic or len(move.number_electronic) != 50:
            raise UserError(
                _(
                    "El REP no tiene una clave electrónica válida de 50 caracteres. "
                    "Es posible que el REP no se haya generado correctamente."
                )
            )

        if not move.xml_comprobante:
            raise UserError(
                _(
                    "Falta el documento XML del REP. Es posible que el REP no se haya generado correctamente."
                )
            )

        if company.frm_ws_ambiente == "disabled":
            raise UserError(
                _("La Facturación Electrónica está deshabilitada para esta compañía.")
            )

        # Get authentication token
        try:
            token = api_facturae.get_token_hacienda(move, company.frm_ws_ambiente)
            if not token:
                raise UserError(
                    _("Error al obtener el token de autenticación de Hacienda.")
                )
        except Exception as e:
            raise UserError(_("Error al obtener el token de Hacienda: %s") % str(e))

        # Query Hacienda for the document status
        try:
            response_json = api_facturae.consulta_clave(
                move.number_electronic, token, company.frm_ws_ambiente
            )
        except Exception as e:
            raise UserError(_("Error al consultar Hacienda: %s") % str(e))

        status = response_json.get("status")
        estado_mh = response_json.get("ind-estado")

        _logger.info(
            "REP %s - Hacienda query result: status=%s, estado=%s",
            move.number_electronic,
            status,
            estado_mh,
        )

        if status == 200:
            # Update status
            move.state_tributacion = estado_mh

            # If accepted or rejected, store the response XML
            if estado_mh in ["aceptado", "rechazado"]:
                respuesta_xml = response_json.get("respuesta-xml")
                if respuesta_xml:
                    move.fname_xml_respuesta_tributacion = (
                        "AHC_" + move.number_electronic + ".xml"
                    )
                    self.env["ir.attachment"].create(
                        {
                            "name": move.fname_xml_respuesta_tributacion,
                            "type": "binary",
                            "datas": respuesta_xml,
                            "res_model": move._name,
                            "res_id": move.id,
                            "res_field": "xml_respuesta_tributacion",
                            "res_name": move.fname_xml_respuesta_tributacion,
                            "mimetype": "text/xml",
                        }
                    )

                if estado_mh == "aceptado":
                    move.electronic_invoice_return_message = _("Aceptado por Hacienda")
                else:
                    move.electronic_invoice_return_message = _("Rechazado por Hacienda")
            else:
                move.electronic_invoice_return_message = _("Estado: %s") % estado_mh

        elif status == 400:
            move.state_tributacion = "ne"
            move.electronic_invoice_return_message = _(
                "Documento no encontrado en Hacienda (puede que no haya sido recibido)"
            )
        else:
            move.electronic_invoice_return_message = (
                _("Error inesperado al consultar Hacienda (estado: %s)") % status
            )

    # -------------------------------------------------------------------------
    # TAX PRORATION CALCULATION
    # -------------------------------------------------------------------------

    def _calculate_rep_proration(self):
        """
        Calculate the tax breakdown for the REP based on paid invoices.

        For partial payments, prorate base and tax amounts proportionally using
        high-precision Decimal arithmetic. Rounding is applied only at the end,
        and any delta is absorbed by a single line (preferably the largest).

        Returns:
            - lines_data: Dict of lines for XML (keyed by line number)
            - tax_breakdown: Summary tax data (for totals)
            - totals: Dict with total_serv_grav, total_serv_exento, total_tax, etc.
        """
        self.ensure_one()

        # === Precision Configuration ===
        # Use 5 decimal places for final XML output
        PRECISION_XML = Decimal("0.00001")

        def to_decimal(val):
            """Convert to Decimal with calculation precision."""
            return Decimal(str(val or 0))

        def round_xml(val):
            """Round to XML output precision."""
            return val.quantize(PRECISION_XML, rounding=ROUND_HALF_UP)

        # Get invoices to process
        invoices = self._get_all_rep_invoices()
        if not invoices:
            return self._generate_simple_rep_line()

        # Calculate payment amount per invoice
        invoice_payments = self._calculate_invoice_payment_amounts(invoices)
        if not invoice_payments:
            return self._generate_simple_rep_line()

        # === Determine if this is a partial or full payment ===
        payment_amount = to_decimal(self.amount)
        total_invoice_amount = sum(to_decimal(inv.amount_total) for inv in invoices)

        # Calculate global proration ratio (high precision)
        if total_invoice_amount > 0:
            global_ratio = payment_amount / total_invoice_amount
        else:
            global_ratio = Decimal("1")

        is_full_payment = (global_ratio >= Decimal("0.9999"))

        # === Aggregate taxes by category with high precision ===
        # Key: (tax_id, tax_code, tax_rate) or 'EXENTO'
        # Value: {'base': Decimal, 'tax': Decimal, 'tax_code': str, ...}
        grouped_data = {}

        for inv, paid_amount in invoice_payments.items():
            paid_decimal = to_decimal(paid_amount)
            if paid_decimal <= Decimal("0.001"):
                continue

            inv_total = to_decimal(inv.amount_total)
            if inv_total <= 0:
                continue

            # Ratio for this specific invoice's payment
            inv_ratio = min(paid_decimal / inv_total, Decimal("1"))

            for line in inv.invoice_line_ids.filtered(
                lambda ln: ln.display_type == "product"
            ):
                line_base = to_decimal(line.price_subtotal)

                if is_full_payment:
                    # Full payment: use exact amounts, no proration
                    prorated_base = line_base
                else:
                    # Partial payment: prorate with high precision
                    prorated_base = line_base * inv_ratio

                if not line.tax_ids:
                    # Exempt line
                    key = "EXENTO"
                    if key not in grouped_data:
                        grouped_data[key] = {
                            "base": Decimal("0"),
                            "tax": Decimal("0"),
                            "tax_code": "00",
                            "tax_rate": Decimal("0"),
                            "iva_tax_code": "",
                            "is_exempt": True,
                        }
                    grouped_data[key]["base"] += prorated_base
                else:
                    for tax in line.tax_ids:
                        tax_code = getattr(tax, "tax_code", "01") or "01"
                        iva_tax_code = getattr(tax, "iva_tax_code", "08") or "08"
                        tax_rate = to_decimal(tax.amount)
                        key = (tax.id, tax_code, float(tax.amount))

                        if key not in grouped_data:
                            grouped_data[key] = {
                                "base": Decimal("0"),
                                "tax": Decimal("0"),
                                "tax_code": tax_code,
                                "tax_rate": tax_rate,
                                "iva_tax_code": iva_tax_code,
                                "tax_name": tax.name,
                                "is_exempt": False,
                            }

                        grouped_data[key]["base"] += prorated_base
                        # Calculate tax from prorated base (high precision)
                        grouped_data[key]["tax"] += prorated_base * tax_rate / Decimal("100")

        # === Build lines_data with rounded values ===
        lines_data = {}
        line_num = 0

        total_serv_grav = Decimal("0")
        total_serv_exento = Decimal("0")
        total_tax = Decimal("0")

        invoice_names = ", ".join(invoices.mapped("name")[:3])
        if len(invoices) > 3:
            invoice_names += "..."

        # Sort groups: taxable lines first (by rate descending), then exempt
        sorted_keys = sorted(
            grouped_data.keys(),
            key=lambda k: (
                grouped_data[k]["is_exempt"],  # False (taxable) before True (exempt)
                -float(grouped_data[k]["tax_rate"]),  # Higher rates first
            )
        )

        for key in sorted_keys:
            data = grouped_data[key]
            # Round base and tax to XML precision
            base = round_xml(data["base"])
            tax_amount = round_xml(data["tax"]) if not data["is_exempt"] else Decimal("0")

            if base < Decimal("0.01"):
                continue

            line_num += 1
            line_total = round_xml(base + tax_amount)

            if data["is_exempt"]:
                description = _("Pago de factura(s) %s - Exento") % invoice_names
                total_serv_exento += base
            else:
                description = _("Pago de factura(s) %s - %s%%") % (
                    invoice_names,
                    int(data["tax_rate"]),
                )
                total_serv_grav += base
                total_tax += tax_amount

            line_dict = {
                "numero_linea": line_num,
                "detalle": description[:160],
                "cantidad": 1,
                "unidadMedida": "Sp",
                "precioUnitario": float(base),
                "montoTotal": float(base),
                "subtotal": float(base),
                "montoTotalLinea": float(line_total),
                "impuesto": {},
                "impuestoNeto": float(tax_amount),
            }

            if not data["is_exempt"] and tax_amount > 0:
                line_dict["impuesto"][1] = {
                    "codigo": data["tax_code"],
                    "tarifa": float(data["tax_rate"]),
                    "monto": float(tax_amount),
                    "iva_tax_code": data["iva_tax_code"],
                }

            lines_data[line_num] = line_dict

        # === Apply single-line rounding adjustment ===
        # Calculate current sum of line totals
        current_sum = sum(
            to_decimal(line["montoTotalLinea"]) for line in lines_data.values()
        )
        delta = round_xml(payment_amount - current_sum)

        if abs(delta) >= PRECISION_XML and lines_data:
            # Find the best line to adjust (prefer largest taxable, then exempt)
            # First check for taxable lines, sorted by montoTotalLinea descending
            taxable_lines = [
                (k, v) for k, v in lines_data.items() if v.get("impuesto")
            ]
            exempt_lines = [
                (k, v) for k, v in lines_data.items() if not v.get("impuesto")
            ]

            taxable_lines.sort(key=lambda x: x[1]["montoTotalLinea"], reverse=True)
            exempt_lines.sort(key=lambda x: x[1]["montoTotalLinea"], reverse=True)

            if taxable_lines:
                # Adjust the largest taxable line's base (not tax)
                adj_key, adj_line = taxable_lines[0]
                old_base = to_decimal(adj_line["subtotal"])
                old_tax = to_decimal(adj_line["impuestoNeto"])
                new_base = round_xml(old_base + delta)
                new_total = round_xml(new_base + old_tax)

                if new_base > 0:
                    adj_line["subtotal"] = float(new_base)
                    adj_line["montoTotal"] = float(new_base)
                    adj_line["precioUnitario"] = float(new_base)
                    adj_line["montoTotalLinea"] = float(new_total)
                    total_serv_grav += delta

            elif exempt_lines:
                # Adjust the largest exempt line
                adj_key, adj_line = exempt_lines[0]
                old_base = to_decimal(adj_line["subtotal"])
                new_base = round_xml(old_base + delta)

                if new_base > 0:
                    adj_line["subtotal"] = float(new_base)
                    adj_line["montoTotal"] = float(new_base)
                    adj_line["precioUnitario"] = float(new_base)
                    adj_line["montoTotalLinea"] = float(new_base)
                    total_serv_exento += delta

        # === Build totals dict ===
        totals = {
            "total_serv_grav": float(round_xml(total_serv_grav)),
            "total_serv_exento": float(round_xml(total_serv_exento)),
            "total_merc_grav": 0.0,
            "total_merc_exento": 0.0,
            "total_tax": float(round_xml(total_tax)),
            "total_venta": float(round_xml(total_serv_grav + total_serv_exento)),
            "total_venta_neta": float(round_xml(total_serv_grav + total_serv_exento)),
            "total_comprobante": float(round_xml(total_serv_grav + total_serv_exento + total_tax)),
        }

        return lines_data, {}, totals

    def _calculate_invoice_payment_amounts(self, invoices):
        """
        Calculate how much of the payment is applied to each invoice.
        Uses the payment amount and distributes it proportionally if needed.
        """
        self.ensure_one()

        payment_amount = self.amount
        invoice_payments = {}

        # For single invoice, use full payment amount
        if len(invoices) == 1:
            return {invoices[0]: payment_amount}

        # For multiple invoices, distribute proportionally by amount_residual
        total_residual = sum(inv.amount_residual for inv in invoices)

        if total_residual <= 0:
            # All invoices fully paid, distribute by total
            total_amount = sum(inv.amount_total for inv in invoices)
            for inv in invoices:
                if total_amount > 0:
                    ratio = inv.amount_total / total_amount
                    invoice_payments[inv] = round(payment_amount * ratio, 5)
        else:
            # Distribute by residual
            for inv in invoices:
                if total_residual > 0:
                    ratio = inv.amount_residual / total_residual
                    invoice_payments[inv] = round(payment_amount * ratio, 5)

        return invoice_payments

    def _generate_simple_rep_line(self):
        """
        Generate a simple REP line when no invoice breakdown is available.
        Uses the payment amount as a single service line.
        """
        self.ensure_one()

        lines_data = {
            1: {
                "numero_linea": 1,
                "detalle": _("Recibo de pago"),
                "cantidad": 1,
                "unidadMedida": "Sp",
                "precioUnitario": self.amount,
                "montoTotal": self.amount,
                "subtotal": self.amount,
                "montoTotalLinea": self.amount,
                "impuesto": {},
                "impuestoNeto": 0.0,
            }
        }

        totals = {
            "total_serv_grav": 0.0,
            "total_serv_exento": self.amount,
            "total_merc_grav": 0.0,
            "total_merc_exento": 0.0,
            "total_tax": 0.0,
            "total_venta": self.amount,
            "total_venta_neta": self.amount,
            "total_comprobante": self.amount,
        }

        return lines_data, {}, totals

    def _apply_rounding_adjustment(
        self, lines_data, total_serv_grav, total_serv_exento, total_tax
    ):
        """
        Apply rounding adjustment to ensure line totals match expected REP total exactly.

        Strategy:
        - Select the largest line to absorb rounding difference (prefer exempt lines).
        - For exempt lines: adjust subtotal/base directly.
        - For taxable lines: adjust subtotal/base, keep tax unchanged, recompute MontoTotalLinea.
        - Ensure no amount becomes negative after adjustment.
        - Update summary totals consistently with the adjustment.
        """
        self.ensure_one()

        # === Precision Configuration ===
        xml_quantizer = Decimal("0.00001")  # 5 decimal places for XML amounts

        def to_xml_precision(val):
            """Convert value to Decimal with XML precision (5 decimals)."""
            return Decimal(str(val)).quantize(xml_quantizer, rounding=ROUND_HALF_UP)

        # === Calculate Expected REP Total ===
        # This is the target that TotalComprobante and sum of lines must match.
        # For single currency (CRC), this equals payment.amount.
        # Note: Multi-currency handling would adjust this value if needed.
        expected_rep_total = to_xml_precision(self.amount)

        # === Calculate Current Lines Total ===
        current_lines_total = sum(
            to_xml_precision(line["montoTotalLinea"]) for line in lines_data.values()
        )

        # === Calculate Rounding Difference ===
        rounding_difference = expected_rep_total - current_lines_total

        # Skip if difference is negligible (within XML precision)
        if abs(rounding_difference) < xml_quantizer:
            return lines_data, total_serv_grav, total_serv_exento, total_tax

        # === Categorize Lines by Tax Status ===
        exempt_lines = [
            (key, line) for key, line in lines_data.items() if not line.get("impuesto")
        ]
        taxable_lines = [
            (key, line) for key, line in lines_data.items() if line.get("impuesto")
        ]

        # Sort by MontoTotalLinea descending (largest first for safer adjustment)
        exempt_lines.sort(
            key=lambda x: to_xml_precision(x[1]["montoTotalLinea"]), reverse=True
        )
        taxable_lines.sort(
            key=lambda x: to_xml_precision(x[1]["montoTotalLinea"]), reverse=True
        )

        # === Select Line to Adjust (prefer exempt, then taxable) ===
        line_to_adjust_key = None
        line_to_adjust = None
        is_exempt_line = False

        if exempt_lines:
            line_to_adjust_key, line_to_adjust = exempt_lines[0]
            is_exempt_line = True
        elif taxable_lines:
            line_to_adjust_key, line_to_adjust = taxable_lines[0]
            is_exempt_line = False

        if not line_to_adjust:
            return lines_data, total_serv_grav, total_serv_exento, total_tax

        # === Apply Adjustment ===
        if is_exempt_line:
            # EXEMPT LINE: Adjust subtotal/base directly
            # MontoTotalLinea = SubTotal (no tax)
            current_subtotal = to_xml_precision(line_to_adjust["subtotal"])
            adjusted_subtotal = current_subtotal + rounding_difference

            # Safety check: prevent negative amounts
            if adjusted_subtotal < Decimal("0"):
                _logger.warning(
                    "Rounding adjustment would create negative subtotal. Skipping."
                )
                return lines_data, total_serv_grav, total_serv_exento, total_tax

            # Update line values
            line_to_adjust["subtotal"] = float(adjusted_subtotal)
            line_to_adjust["montoTotal"] = float(adjusted_subtotal)
            line_to_adjust["precioUnitario"] = float(
                adjusted_subtotal
            )  # Assuming qty=1
            line_to_adjust["montoTotalLinea"] = float(adjusted_subtotal)

            # Update summary total for exempt services
            total_serv_exento = float(
                to_xml_precision(total_serv_exento) + rounding_difference
            )

        else:
            # TAXABLE LINE: Adjust subtotal/base, keep tax unchanged
            # MontoTotalLinea = SubTotal + ImpuestoNeto
            current_subtotal = to_xml_precision(line_to_adjust["subtotal"])
            current_tax = to_xml_precision(line_to_adjust["impuestoNeto"])
            adjusted_subtotal = current_subtotal + rounding_difference

            # Safety check: prevent negative amounts
            if adjusted_subtotal < Decimal("0"):
                _logger.warning(
                    "Rounding adjustment would create negative subtotal. Skipping."
                )
                return lines_data, total_serv_grav, total_serv_exento, total_tax

            # Recompute MontoTotalLinea maintaining invariant: SubTotal + ImpuestoNeto
            adjusted_monto_total_linea = adjusted_subtotal + current_tax

            # Update line values (convert to float for consistency with rest of code)
            line_to_adjust["subtotal"] = float(adjusted_subtotal)
            line_to_adjust["montoTotal"] = float(adjusted_subtotal)
            line_to_adjust["precioUnitario"] = float(
                adjusted_subtotal
            )  # Assuming qty=1
            line_to_adjust["montoTotalLinea"] = float(adjusted_monto_total_linea)
            # Note: impuestoNeto and impuesto[x]["monto"] remain unchanged

            # Update summary total for taxable services (base changed, not tax)
            total_serv_grav = float(
                to_xml_precision(total_serv_grav) + rounding_difference
            )

        return lines_data, total_serv_grav, total_serv_exento, total_tax

    # -------------------------------------------------------------------------
    # CRON: SEND REP TO HACIENDA
    # -------------------------------------------------------------------------

    @api.model
    def _send_rep_to_hacienda_cron(self, max_payments=10):
        """
        Cron job to send pending REP documents to Hacienda.

        REP Lifecycle:
        - False / 'ne'   → Generated but not sent (picked up by this cron)
        - 'procesando'   → Sent to Hacienda, awaiting response
        - 'recibido'     → Received by Hacienda
        - 'aceptado'     → Accepted by Hacienda (terminal)
        - 'rechazado'    → Rejected by Hacienda (terminal, requires user action)
        - 'error'        → Error during send/process

        Idempotency: Only sends documents not yet sent (state False/ne).
        Documents already in 'procesando', 'aceptado', etc. are never re-sent.
        """
        _logger.info("##### CRON - Envía REP a Hacienda")

        moves = self.env["account.move"].search(
            [
                ("tipo_documento", "=", "REP"),
                ("number_electronic", "!=", False),
                ("xml_comprobante", "!=", False),
                "|",
                ("state_tributacion", "=", False),
                ("state_tributacion", "=", "ne"),
            ],
            order="id asc",
            limit=max_payments,
        )

        total_moves = len(moves)
        if total_moves == 0:
            _logger.info("E-INV CR - No pending REP to send")
            return

        _logger.info("E-INV CR - REP to send: %s", total_moves)

        current = 0
        for move in moves:
            current += 1
            _logger.info(
                "E-INV CR - Sending REP %s / %s - %s",
                current,
                total_moves,
                move.number_electronic,
            )
            try:
                # Find the payment associated with this move
                payment = self.env["account.payment"].search(
                    [("move_id", "=", move.id)], limit=1
                )
                if payment:
                    payment._send_rep_to_hacienda()
                else:
                    _logger.warning(
                        "E-INV CR - REP move %s has no associated payment",
                        move.number_electronic,
                    )
                    move.state_tributacion = "error"
                    move.electronic_invoice_return_message = _(
                        "No se encontró el pago asociado al REP"
                    )
            except Exception as e:
                _logger.exception(
                    "E-INV CR - Error sending REP %s: %s",
                    move.number_electronic,
                    e,
                )
                move.state_tributacion = "error"
                move.electronic_invoice_return_message = str(e)

        _logger.info("E-INV CR - _send_rep_to_hacienda_cron - Completed")

    # -------------------------------------------------------------------------
    # CRON: CHECK REP STATUS FROM HACIENDA
    # -------------------------------------------------------------------------

    @api.model
    def _check_hacienda_for_rep(self, max_payments=10):
        """
        Cron job to check the status of REP documents in Hacienda.

        REP Lifecycle (check phase):
        - 'procesando' → Sent, awaiting Hacienda response (query status)
        - 'recibido'   → Received by Hacienda (query for final status)
        - 'ne'         → Not found in previous query (retry)
        - 'aceptado'   → Terminal state, no further queries
        - 'rechazado'  → Terminal state, no further queries
        - 'error'      → Terminal state, requires user intervention

        Terminal states ('aceptado', 'rechazado', 'error') are NOT queried.
        """
        _logger.info("##### CRON - Consulta Estado de REP")

        # Search on account.move directly for REP documents awaiting status
        moves = self.env["account.move"].search(
            [
                ("tipo_documento", "=", "REP"),
                ("number_electronic", "!=", False),
                ("xml_comprobante", "!=", False),
                ("state_tributacion", "in", ["procesando", "recibido", "ne"]),
            ],
            order="id asc",
            limit=max_payments,
        )

        total_moves = len(moves)
        if total_moves == 0:
            _logger.info("E-INV CR - No REP to check status")
            return

        _logger.info("E-INV CR - REP to check: %s", total_moves)

        current = 0
        for move in moves:
            current += 1
            company = move.company_id

            _logger.info(
                "E-INV CR - Checking REP %s / %s - %s",
                current,
                total_moves,
                move.number_electronic,
            )

            try:
                # Validate prerequisites
                if not move.number_electronic or len(move.number_electronic) != 50:
                    move.state_tributacion = "error"
                    _logger.warning(
                        "E-INV CR - REP %s has invalid electronic number. Status: error",
                        move.name,
                    )
                    continue

                if not move.xml_comprobante:
                    move.state_tributacion = "error"
                    _logger.warning(
                        "E-INV CR - REP %s has no XML document. Status: error",
                        move.number_electronic,
                    )
                    continue

                # Get authentication token
                token = api_facturae.get_token_hacienda(move, company.frm_ws_ambiente)
                if not token:
                    _logger.error(
                        "E-INV CR - Failed to get Hacienda token for REP %s",
                        move.number_electronic,
                    )
                    continue

                # Query Hacienda
                response_json = api_facturae.consulta_clave(
                    move.number_electronic, token, company.frm_ws_ambiente
                )
                status = response_json.get("status")
                estado_mh = response_json.get("ind-estado")

                _logger.info(
                    "E-INV CR - REP %s status: %s, estado: %s",
                    move.number_electronic,
                    status,
                    estado_mh,
                )

                if status == 200:
                    move.state_tributacion = estado_mh

                    if estado_mh == "aceptado":
                        # Store response XML
                        respuesta_xml = response_json.get("respuesta-xml")
                        if respuesta_xml:
                            move.fname_xml_respuesta_tributacion = (
                                "AHC_" + move.number_electronic + ".xml"
                            )
                            self.env["ir.attachment"].create(
                                {
                                    "name": move.fname_xml_respuesta_tributacion,
                                    "type": "binary",
                                    "datas": respuesta_xml,
                                    "res_model": move._name,
                                    "res_id": move.id,
                                    "res_field": "xml_respuesta_tributacion",
                                    "res_name": move.fname_xml_respuesta_tributacion,
                                    "mimetype": "text/xml",
                                }
                            )
                        move.electronic_invoice_return_message = _(
                            "Aceptado por Hacienda"
                        )

                    elif estado_mh == "rechazado":
                        # Store response XML
                        respuesta_xml = response_json.get("respuesta-xml")
                        if respuesta_xml:
                            move.fname_xml_respuesta_tributacion = (
                                "AHC_" + move.number_electronic + ".xml"
                            )
                            self.env["ir.attachment"].create(
                                {
                                    "name": move.fname_xml_respuesta_tributacion,
                                    "type": "binary",
                                    "datas": respuesta_xml,
                                    "res_model": move._name,
                                    "res_id": move.id,
                                    "res_field": "xml_respuesta_tributacion",
                                    "res_name": move.fname_xml_respuesta_tributacion,
                                    "mimetype": "text/xml",
                                }
                            )
                        move.electronic_invoice_return_message = _(
                            "Rechazado por Hacienda"
                        )

                elif status == 400:
                    move.state_tributacion = "ne"
                    _logger.warning(
                        "E-INV CR - REP %s not found in Hacienda. Status: ne",
                        move.number_electronic,
                    )

                else:
                    _logger.error(
                        "E-INV CR - Unexpected error checking REP %s. Status: %s",
                        move.number_electronic,
                        status,
                    )

            except Exception as e:
                _logger.exception(
                    "E-INV CR - Error checking REP %s: %s",
                    move.number_electronic,
                    e,
                )

        _logger.info("E-INV CR - _check_hacienda_for_rep - Completed")
