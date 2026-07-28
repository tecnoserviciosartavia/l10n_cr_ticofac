# -*- coding: utf-8 -*-
"""
POS Order Extension for Costa Rica Electronic Invoicing

This module extends pos.order to support electronic invoicing (FE) in Point of Sale.
It uses fe.validation.service for validation logic to ensure consistency
with the Sales module (account.move) validations.
"""
import logging
from threading import Lock

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

lock = Lock()

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _name = "pos.order"
    _description = "PosOrder"
    _inherit = "pos.order"

    tipo_documento = fields.Selection(
        selection=[
            ("FE", "Electronic Invoice"),
            ("TE", "Electronic Ticket"),
            ("NC", "Electronic Credit Note"),
        ],
        string="Receipt Type",
        default="TE",
        help="Show document type in concordance with Ministerio de Hacienda classification",
    )

    payment_methods_id = fields.Many2one(
        comodel_name="payment.methods", string="Payment methods"
    )

    number_electronic = fields.Char(string="Electronic Number", copy=False, index=True)
    sequence = fields.Char(string="Consecutive", readonly=True)
    journal_id = fields.Char(string="Journal ID", copy=False)

    # Refund / Credit Note Fields
    refund_reason = fields.Char(string="Refund Reason")
    refund_reference_code_id = fields.Many2one(
        comodel_name="reference.code", string="Reference Code"
    )

    # =========================================================================
    # CREATE/WRITE OVERRIDES - Odoo 18 POS passes data directly to create/write
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        """Override to handle refund_reference_code_id from POS frontend."""
        for vals in vals_list:
            # The value might come as integer from frontend, ensure it's properly handled
            ref_code_id = vals.get("refund_reference_code_id")
            if ref_code_id and not isinstance(ref_code_id, bool):
                try:
                    vals["refund_reference_code_id"] = int(ref_code_id)
                except (ValueError, TypeError) as e:
                    _logger.error(f"Failed to convert refund_reference_code_id: {e}")

        return super().create(vals_list)

    def write(self, vals):
        """Override to handle refund_reference_code_id from POS frontend."""
        # The value might come as integer from frontend, ensure it's properly handled
        ref_code_id = vals.get("refund_reference_code_id")
        if ref_code_id and not isinstance(ref_code_id, bool):
            try:
                vals["refund_reference_code_id"] = int(ref_code_id)
            except (ValueError, TypeError) as e:
                _logger.error(f"Failed to convert refund_reference_code_id: {e}")

        return super().write(vals)

    # =========================================================================
    # FE VALIDATION METHODS
    # Note: Core validation logic is provided by fe.validation.service
    # The methods below are POS-specific wrappers and API endpoints
    # =========================================================================

    def _get_validation_service(self):
        """Get the FE validation service."""
        return self.env["fe.validation.service"]

    def _should_validate_partner_for_fe(self):
        """
        Determine if this POS order requires strict partner validation.

        Returns:
            bool: True if strict validation is required
        """
        self.ensure_one()

        # Only validate if electronic invoicing is enabled
        if not self.company_id.invoice_is_electronic:
            return False

        # Document types that require strict validation
        strict_doc_types = ("FE", "FEE", "NC", "ND")

        # TE doesn't require strict validation
        if self.tipo_documento == "TE":
            return False

        # NC specific logic: Check if it's a refund for a TE
        if self.tipo_documento == "NC":
            # Check original orders from refunded lines
            try:
                original_orders = self.lines.mapped("refunded_orderline_id.order_id")
                # If any original order is a TE, relax validation (allow generic client)
                # Typically a generic client refund shouldn't require full data
                for origin in original_orders:
                    if origin.tipo_documento == "TE":
                        _logger.info(
                            "Skipping strict partner validation for NC of a TE"
                        )
                        return False
            except Exception as e:
                _logger.warning(
                    f"Error checking original order type for NC validation: {e}"
                )

        # FE, NC (default), ND, FEE require strict validation
        if self.tipo_documento in strict_doc_types:
            return True

        return False

    def _validate_pos_order_for_fe(self):
        """
        Validate the POS order for electronic invoicing.
        Validates both partner data and CABYS codes.
        Called before invoice generation to ensure data is complete.

        Raises:
            UserError: If validation fails (partner data or CABYS codes incomplete)
        """
        self.ensure_one()

        validation_service = self._get_validation_service()

        # Skip validation if not required
        # Note: We rely on _should_validate_partner_for_fe for internal logic
        if (
            not validation_service.should_validate_for_fe(
                self.tipo_documento, self.company_id
            )
            and self.tipo_documento != "NC"
        ):
            return True

        # Use our smarter local checks
        requires_partner = self._should_validate_partner_for_fe()

        partner = self.partner_id

        # For FE document types, partner is required (unless relaxed by logic above)
        if requires_partner and not partner:
            raise UserError(
                _(
                    "⚠️ No se puede generar la Factura Electrónica.\n\n"
                    "El pedido no tiene un cliente asignado.\n"
                    "Por favor seleccione un cliente antes de continuar."
                )
            )

        # Validate partner if required
        if requires_partner:
            is_valid, missing_fields = validation_service.validate_partner_for_fe(
                partner, self.tipo_documento
            )
            if not is_valid:
                validation_service.raise_partner_validation_error(
                    partner, self.tipo_documento, missing_fields
                )

        # Validate CABYS for all document types
        # Get POS order lines
        product_lines = self.lines
        cabys_valid, cabys_errors = validation_service.validate_cabys_for_lines(
            product_lines, partner
        )
        if not cabys_valid:
            validation_service.raise_cabys_validation_error(
                self.tipo_documento, cabys_errors
            )

        return True

    # =========================================================================
    # API METHODS FOR POS FRONTEND
    # =========================================================================

    @api.model
    def validate_order_for_pos_fe(
        self,
        partner_id,
        tipo_documento,
        line_product_ids,
        company_id=None,
        original_tipo_documento=False,
        refunded_orderline_ids=None,
    ):
        """
        API method to validate order data for POS electronic invoicing.
        Called from the POS frontend before submitting the order.

        This method validates both partner data AND CABYS codes in a single call,
        providing comprehensive validation feedback to the user.

        Args:
            partner_id: int - ID of the res.partner to validate
            tipo_documento: str - Document type (FE, TE, NC, ND, FEE)
            line_product_ids: list of int - IDs of products in order lines
            company_id: int - Optional company ID for context
            original_tipo_documento: str - Type of the original document (if NC)
            refunded_orderline_ids: list of int - IDs of refunded order lines (for NC)

        Returns:
            dict: {
                'valid': bool,
                'partner_valid': bool,
                'partner_missing_fields': list,
                'cabys_valid': bool,
                'cabys_errors': list of {'product_name': str, 'error_type': str},
                'error_message': str - Complete error message if invalid
            }
        """
        result = {
            "valid": True,
            "partner_valid": True,
            "partner_missing_fields": [],
            "cabys_valid": True,
            "cabys_errors": [],
            "error_message": "",
        }

        # Check if company has electronic invoicing enabled
        company = self.env.company
        if company_id:
            company = self.env["res.company"].browse(company_id)

        if not company.invoice_is_electronic:
            return result

        validation_service = self.env["fe.validation.service"]
        error_messages = []

        # -------------------------------------------------------------------------
        # PARTNER VALIDATION
        # -------------------------------------------------------------------------
        # TE doesn't require strict partner validation
        # NC depends on the original document type
        requires_strict_validation = False

        # For NC, try to determine original document type
        if tipo_documento == "NC" and not original_tipo_documento:
            # Look up the original order's tipo_documento from refunded lines
            if refunded_orderline_ids:
                try:
                    refunded_lines = self.env["pos.order.line"].browse(
                        refunded_orderline_ids
                    )
                    original_orders = refunded_lines.mapped("order_id")
                    if original_orders:
                        original_tipo_documento = original_orders[0].tipo_documento
                        _logger.info(
                            f"NC validation: Detected original tipo_documento={original_tipo_documento} from refunded lines"
                        )
                except Exception as e:
                    _logger.warning(
                        f"NC validation: Could not determine original tipo_documento: {e}"
                    )
            else:
                _logger.warning("NC validation: No refunded_orderline_ids provided")

        if tipo_documento == "TE":
            requires_strict_validation = False
        elif tipo_documento == "NC":
            # For NC, check original document type
            # If frontend didn't provide it, try to look it up from line_product_ids context
            # For now, if original_tipo_documento is explicitly "TE", skip validation
            # Otherwise, we need to be conservative and require validation
            if original_tipo_documento == "TE":
                requires_strict_validation = False
                _logger.info("NC for TE detected - skipping strict partner validation")
            elif original_tipo_documento:
                # Original is FE or other - require strict validation
                requires_strict_validation = True
            else:
                # original_tipo_documento not provided - try to detect from current session orders
                # This is a fallback when frontend couldn't determine the original type
                # Default to requiring validation (safer) - user can fix data if needed
                _logger.warning(
                    "NC validation: original_tipo_documento not provided, defaulting to strict validation"
                )
                requires_strict_validation = True
        elif tipo_documento in ("FE", "FEE", "ND"):
            requires_strict_validation = True

        if requires_strict_validation:
            if not partner_id:
                result["valid"] = False
                result["partner_valid"] = False
                result["partner_missing_fields"] = [_("Cliente")]
                error_messages.append(
                    _(
                        "⚠️ No se puede generar la Documento Electrónico (%s).\n\n"
                        "El pedido no tiene un cliente asignado.\n"
                        "Por favor seleccione un cliente antes de continuar."
                    )
                    % tipo_documento
                )
            else:
                partner = self.env["res.partner"].browse(partner_id)
                if not partner.exists():
                    result["valid"] = False
                    result["partner_valid"] = False
                    result["partner_missing_fields"] = [_("Cliente")]
                    error_messages.append(_("El cliente seleccionado no existe."))
                else:
                    # Use validation service
                    is_valid, missing_fields = (
                        validation_service.validate_partner_for_fe(
                            partner, tipo_documento
                        )
                    )
                    result["partner_valid"] = is_valid
                    result["partner_missing_fields"] = missing_fields

                    if not is_valid:
                        result["valid"] = False
                        error_messages.append(
                            validation_service.format_partner_validation_error(
                                partner, tipo_documento, missing_fields
                            )
                        )

        # -------------------------------------------------------------------------
        # CABYS VALIDATION
        # -------------------------------------------------------------------------
        if line_product_ids:
            products = self.env["product.product"].browse(line_product_ids)
            partner = self.env["res.partner"].browse(partner_id) if partner_id else None

            # Create pseudo-lines for validation
            class PseudoLine:
                def __init__(self, product):
                    self.product_id = product
                    self.display_type = "product"

            pseudo_lines = [PseudoLine(p) for p in products if p.exists()]

            cabys_valid, cabys_errors = validation_service.validate_cabys_for_lines(
                pseudo_lines, partner
            )
            result["cabys_valid"] = cabys_valid
            result["cabys_errors"] = [
                {"product_name": e["product_name"], "error_type": e["error_type"]}
                for e in cabys_errors
            ]

            if not cabys_valid:
                result["valid"] = False
                error_messages.append(
                    validation_service.format_cabys_validation_error(
                        tipo_documento, cabys_errors
                    )
                )

        # Combine error messages
        if error_messages:
            result["error_message"] = "\n\n".join(error_messages)

        return result

    @api.model
    def validate_discount_codes_for_pos(self, lines_data, company_id=None):
        """
        API method to validate discount codes for POS lines BEFORE order submission.
        Called from the POS frontend to validate discount codes.

        Args:
            lines_data: list of dicts with {'product_name': str, 'discount': float, 'discount_code_id': int or False}
            company_id: int - Optional company ID for context

        Returns:
            dict: {
                'valid': bool,
                'missing_codes': list of product names missing discount codes,
                'error_message': str - Error message if invalid
            }
        """
        result = {
            "valid": True,
            "missing_codes": [],
            "error_message": "",
        }

        # Check if company has electronic invoicing enabled
        company = self.env.company
        if company_id:
            company = self.env["res.company"].browse(company_id)

        if not company.invoice_is_electronic:
            return result

        # Check each line for missing discount codes
        missing_codes = []
        for line_data in lines_data:
            discount = line_data.get("discount", 0)
            discount_code_id = line_data.get("discount_code_id")
            product_name = line_data.get("product_name", _("Unknown Product"))

            if discount and discount > 0 and not discount_code_id:
                missing_codes.append(product_name)

        if missing_codes:
            result["valid"] = False
            result["missing_codes"] = missing_codes
            products_list = "\n".join([f"  • {name}" for name in missing_codes])
            result["error_message"] = (
                _(
                    "⚠️ No se puede generar la Factura Electrónica.\n\n"
                    "Los siguientes productos tienen un descuento aplicado pero no tienen un código de descuento seleccionado:\n\n"
                    "%s\n\n"
                    "Por favor seleccione un código de descuento para cada línea con descuento antes de continuar."
                )
                % products_list
            )

        return result

    # =========================================================================
    # INVOICE GENERATION METHODS
    # =========================================================================

    def _prepare_invoice_vals(self):
        """Override to include custom fields in account.move."""
        vals = super()._prepare_invoice_vals()
        journal = self.session_id.config_id.invoice_journal_id
        if not journal or journal.type != "sale":
            raise ValidationError(
                "The selected journal is not a sales journal. Please check POS settings."
            )

        # Determinar si es una Nota de Crédito (Refund)
        is_refund = self.amount_total < 0
        tipo_documento = "NC" if is_refund else self.tipo_documento

        # Obtener la secuencia de facturación del diario
        sequence_code = False
        if journal.FE_sequence_id or journal.TE_sequence_id:
            if tipo_documento == "FE":
                sequence_code = journal.FE_sequence_id.next_by_id()
            elif tipo_documento == "TE":
                sequence_code = journal.TE_sequence_id.next_by_id()
            elif tipo_documento == "NC" and journal.NC_sequence_id:
                sequence_code = journal.NC_sequence_id.next_by_id()
        else:
            raise ValidationError(
                _("The selected journal does not have an assigned sequence.")
            )

        # Get payment method ID safely
        payment_method_ids = self.payment_ids.mapped(
            "payment_method_id"
        ).account_payment_method_id
        payment_method_id = False
        if payment_method_ids:
            payment_method_id = (
                payment_method_ids[0].id if len(payment_method_ids) >= 1 else False
            )

        vals.update(
            {
                "company_id": self.company_id.id,
                "journal_id": journal.id,  # Set the correct sales journal.
                "invoice_date": False,
                "tipo_documento": tipo_documento,
                "sequence": (
                    self.number_electronic[21:41] if self.number_electronic else False
                ),
                "number_electronic": self.number_electronic,
                "name": (
                    self.number_electronic[21:41] if self.number_electronic else False
                ),
                "payment_methods_id": payment_method_id,
                "economic_activity_id": (
                    self.company_id.activity_id.id
                    if self.company_id.activity_id
                    else False
                ),
            }
        )

        # Logic for Credit Notes
        if is_refund:
            vals["move_type"] = "out_refund"
            vals["ref"] = self.refund_reason

            # 1. Reference Code (Reason Type)
            # Use the provided refund_reference_code_id.
            # If missing the validation in account.move will catch the missing field.
            if self.refund_reference_code_id:
                vals["reference_code_id"] = self.refund_reference_code_id.id

            # 2. Reference Document (Original Invoice)
            # Find original order via refunded lines
            original_orders = self.lines.mapped("refunded_orderline_id.order_id")
            if original_orders:
                original_order = original_orders[0]
                if original_order.account_move:
                    vals["invoice_id"] = original_order.account_move.id

                    doc_type_map = {
                        "FE": "01",
                        "TE": "04",
                        "FEE": "01",
                    }

                    if original_order.tipo_documento not in doc_type_map:
                        raise UserError(
                            _(
                                "No se puede generar una Nota de Crédito para un documento de tipo %s.\nSolamente se permiten Notas de Crédito para Facturas Electrónicas (FE, FEE) y Tiquetes Electrónicos (TE)."
                            )
                            % original_order.tipo_documento
                        )

                    ref_doc_code = doc_type_map.get(original_order.tipo_documento)

                    ref_doc = self.env["reference.document"].search(
                        [("code", "=", ref_doc_code)], limit=1
                    )
                    if ref_doc:
                        vals["reference_document_id"] = ref_doc.id
                    else:
                        _logger.warning(
                            f"No se encontró el tipo de documento de referencia para el código {ref_doc_code}"
                        )
                        ref_doc_fallback = self.env["reference.document"].search(
                            [("code", "=", "01")], limit=1
                        )
                        if ref_doc_fallback:
                            vals["reference_document_id"] = ref_doc_fallback.id

        return vals

    def _order_fields(self, ui_order):
        vals = super()._order_fields(ui_order)
        vals["tipo_documento"] = ui_order.get("tipo_documento")
        vals["sequence"] = ui_order.get("sequence")
        vals["number_electronic"] = ui_order.get("number_electronic")
        vals["refund_reason"] = ui_order.get("refund_reason")

        # Handle refund_reference_code_id
        ref_code_id = ui_order.get("refund_reference_code_id")
        if not ref_code_id and "data" in ui_order:
            ref_code_id = ui_order.get("data", {}).get("refund_reference_code_id")

        if ref_code_id:
            try:
                vals["refund_reference_code_id"] = int(ref_code_id)
            except (ValueError, TypeError):
                _logger.error(
                    f"POS Order: Invalid refund_reference_code_id value: {ref_code_id}"
                )

        return vals

    @api.model
    def _process_order(self, order, existing_order):
        """Override to process order data from UI."""
        return super()._process_order(order, existing_order)

    def _get_invoice_lines_values(self, line_values, pos_line):
        """Override to include discount_code_id in invoice line."""
        invoice_line_vals = super()._get_invoice_lines_values(line_values, pos_line)
        # Add discount_code_id from POS order line to invoice line
        if pos_line.discount_code_id:
            invoice_line_vals["discount_code_id"] = pos_line.discount_code_id.id
        return invoice_line_vals

    def _validate_discount_codes(self):
        """
        Validate that all POS order lines with a discount have a discount code.
        Skip validation for Credit Notes (NC) as they inherit discount codes from the original document.

        Raises:
            UserError: If any line has a discount but no discount code
        """
        self.ensure_one()

        # Skip validation if not electronic invoicing company
        if not self.company_id.invoice_is_electronic:
            return True

        # Skip validation for Credit Notes (NC) / Refunds
        # NC inherits discount codes from the original document being refunded
        if self.tipo_documento == "NC":
            _logger.info(
                "Skipping discount code validation for NC (Credit Note) order %s",
                self.name,
            )
            return True

        lines_missing_code = []
        for line in self.lines:
            # Check if line has a discount percentage but no discount code
            if line.discount and line.discount > 0 and not line.discount_code_id:
                product_name = (
                    line.product_id.display_name
                    or line.full_product_name
                    or _("Unknown Product")
                )
                lines_missing_code.append(product_name)

        if lines_missing_code:
            products_list = "\n".join([f"  • {name}" for name in lines_missing_code])
            raise UserError(
                _(
                    "⚠️ No se puede generar la Factura Electrónica.\n\n"
                    "Los siguientes productos tienen un descuento aplicado pero no tienen un código de descuento seleccionado:\n\n"
                    "%s\n\n"
                    "Por favor seleccione un código de descuento para cada línea con descuento antes de continuar."
                )
                % products_list
            )

        return True

    def _generate_pos_order_invoice(self):
        """Genera la factura del POS, la publica y aplica los pagos para que quede pagada.

        IMPORTANT: This method validates client/partner data AND CABYS codes BEFORE creating the invoice.
        If validation fails, a UserError will be raised and propagated to the POS frontend.
        """
        self.ensure_one()

        # -------------------------------------------------------------------------
        # FULL FE VALIDATION (Client + CABYS + Discount Codes)
        # -------------------------------------------------------------------------
        # Validate all FE requirements BEFORE creating invoice to prevent:
        # 1. Silent failures where invoice is not generated but POS continues
        # 2. Invalid XML generation that would be rejected by Hacienda
        # This validation will raise UserError if data is incomplete
        self._validate_pos_order_for_fe()

        # Validate discount codes - must have a code for each line with discount
        self._validate_discount_codes()

        # Paso 1: crear factura con los vals preparados
        vals = self._prepare_invoice_vals()
        invoice = self.env["account.move"].sudo().create(vals)

        # Paso 2: publicar la factura (si está en borrador)
        if invoice.state == "draft":
            invoice.action_post()

        # Paso 3: linkear la factura con el pedido
        self.write({"account_move": invoice.id})

        # Paso 4: aplicar pagos del POS (conciliar automáticamente)
        if self.payment_ids:
            try:
                self._apply_invoice_payments(self.session_id.state == "closed")
                _logger.info(
                    f"💰 Pagos aplicados y conciliados a la factura {invoice.name} del pedido {self.name}"
                )
            except Exception as e:
                _logger.error(
                    f"⚠️ Error al conciliar pagos para la factura {invoice.name}: {e}"
                )

        _logger.info(
            f"✅ Factura {invoice.name} generada y publicada para orden {self.name}"
        )

        return invoice
