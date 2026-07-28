# -*- coding: utf-8 -*-
"""
Electronic Invoice Validation Service

This module provides a shared validation service for Costa Rica Electronic Invoicing (FE).
It contains validation logic for:
- Partner/Customer data validation
- CABYS (Código de Actividad de Bienes y Servicios) validation

This service model is designed to be called from both account.move and pos.order models
to avoid code duplication and ensure consistent validation across modules.

Usage:
    validation_service = self.env['fe.validation.service']
    is_valid, missing = validation_service.validate_partner_for_fe(partner, tipo_documento)
"""
import logging
import re

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FEValidationService(models.AbstractModel):
    """
    Service model providing electronic invoicing validation methods.

    This abstract model provides reusable validation methods for:
    - Partner data validation (identification, email, address)
    - CABYS code validation for product lines

    Both account.move and pos.order can call this service's methods
    to share the same validation logic without inheritance issues.
    """

    _name = "fe.validation.service"
    _description = "FE Validation Service"

    # =========================================================================
    # DOCUMENT TYPE LABELS (Shared)
    # =========================================================================

    @api.model
    def get_fe_doc_type_labels(self):
        """Get document type labels for error messages."""
        return {
            "FE": _("Factura Electrónica"),
            "FEE": _("Factura de Exportación"),
            "NC": _("Nota de Crédito"),
            "ND": _("Nota de Débito"),
            "TE": _("Tiquete Electrónico"),
        }

    # =========================================================================
    # EMAIL VALIDATION (Shared)
    # =========================================================================

    @api.model
    def is_valid_email(self, email):
        """
        Validate email format using the same regex as the XML generation.

        Args:
            email: Email string to validate

        Returns:
            bool: True if email is valid
        """
        if not email:
            return False
        re_match = r"^(\s?[^\s,]+@[^\s,]+\.[^\s,]+\s?,)*(\s?[^\s,]+@[^\s,]+\.[^\s,]+)$"
        return bool(re.match(re_match, email.lower()))

    # =========================================================================
    # PARTNER VALIDATION (Shared)
    # =========================================================================

    @api.model
    def get_required_partner_fields_for_fe(
        self, tipo_documento, partner, reference_document=None
    ):
        """
        Get required partner fields based on document type.

        Args:
            tipo_documento: Document type code (FE, TE, NC, ND, FEE, etc.)
            partner: res.partner record
            reference_document: Optional reference document for NC validation

        Returns:
            dict: {
                'field_name': {
                    'label': 'Human-readable field name',
                    'check': lambda: boolean expression to validate field
                }
            }
        """
        # TE documents don't include Receptor section in XML
        if tipo_documento == "TE":
            return {
                "name": {
                    "label": _("Nombre del Cliente"),
                    "check": lambda: bool(partner.name),
                }
            }

        # NC referencing a TE also skips strict validation
        if tipo_documento == "NC" and reference_document:
            # Check if reference_document has code '04' (TE)
            if hasattr(reference_document, "code") and reference_document.code == "04":
                return {
                    "name": {
                        "label": _("Nombre del Cliente"),
                        "check": lambda: bool(partner.name),
                    }
                }

        # Base required fields for all FE documents (FE, FEE, NC, ND)
        required_fields = {
            "name": {
                "label": _("Nombre del Cliente"),
                "check": lambda: bool(partner.name),
            },
            "vat": {
                "label": _("Cédula / Identificación"),
                "check": lambda: bool(
                    partner.vat and re.sub("[^0-9]", "", partner.vat)
                ),
            },
            "email": {
                "label": _("Correo Electrónico"),
                "check": lambda: bool(
                    partner.email and self.is_valid_email(partner.email)
                ),
            },
        }

        # FE, NC, ND require full address (not FEE - export invoices)
        if tipo_documento in ("FE", "NC", "ND"):
            required_fields.update(
                {
                    "state_id": {
                        "label": _("Provincia"),
                        "check": lambda: bool(
                            partner.state_id and partner.state_id.code
                        ),
                    },
                    "county_id": {
                        "label": _("Cantón"),
                        "check": lambda: bool(
                            partner.county_id and partner.county_id.code
                        ),
                    },
                    "district_id": {
                        "label": _("Distrito"),
                        "check": lambda: bool(
                            partner.district_id and partner.district_id.code
                        ),
                    },
                    "street": {
                        "label": _("Dirección Exacta / Otras Señas"),
                        "check": lambda: bool(partner.street),
                    },
                }
            )

        return required_fields

    @api.model
    def validate_partner_for_fe(self, partner, tipo_documento, reference_document=None):
        """
        Validate partner has all required fields for the given document type.

        Args:
            partner: res.partner record to validate
            tipo_documento: Document type code (FE, TE, NC, ND, FEE, etc.)
            reference_document: Optional reference document for NC validation

        Returns:
            tuple: (is_valid: bool, missing_fields: list of field labels)
        """
        if not partner:
            return False, [_("Cliente")]

        required_fields = self.get_required_partner_fields_for_fe(
            tipo_documento, partner, reference_document
        )
        missing_fields = []

        for field_name, field_config in required_fields.items():
            try:
                if not field_config["check"]():
                    missing_fields.append(field_config["label"])
            except Exception:
                # If check fails due to missing related field, consider it missing
                missing_fields.append(field_config["label"])

        is_valid = len(missing_fields) == 0
        return is_valid, missing_fields

    @api.model
    def format_partner_validation_error(self, partner, tipo_documento, missing_fields):
        """
        Format partner validation error message.

        Args:
            partner: res.partner record
            tipo_documento: Document type code
            missing_fields: list of missing field labels

        Returns:
            str: Formatted error message
        """
        doc_type_labels = self.get_fe_doc_type_labels()
        doc_label = doc_type_labels.get(tipo_documento, tipo_documento)
        missing_list = "\n  • " + "\n  • ".join(missing_fields)

        return _(
            "⚠️ No se puede generar el documento electrónico (%s).\n\n"
            'El cliente "%s" tiene datos faltantes requeridos por Hacienda:\n'
            "%s\n\n"
            "Por favor complete la información en la ficha del contacto antes de continuar."
        ) % (doc_label, partner.name or _("Desconocido"), missing_list)

    @api.model
    def raise_partner_validation_error(self, partner, tipo_documento, missing_fields):
        """
        Raise a UserError with a clear message about missing partner fields.

        Args:
            partner: res.partner record
            tipo_documento: Document type code
            missing_fields: list of missing field labels
        """
        error_message = self.format_partner_validation_error(
            partner, tipo_documento, missing_fields
        )
        raise UserError(error_message)

    # =========================================================================
    # CABYS VALIDATION (Shared)
    # =========================================================================

    @api.model
    def validate_cabys_for_line(self, product, partner=None):
        """
        Validate CABYS code for a single product.

        Args:
            product: product.product record
            partner: Optional res.partner record (for exoneration validation)

        Returns:
            dict: {
                'valid': bool,
                'cabys_code': str or None,
                'error_type': str or None ('missing', 'not_approved'),
                'error_message': str or None
            }
        """
        result = {
            "valid": True,
            "cabys_code": None,
            "error_type": None,
            "error_message": None,
            "product_name": product.name if product else _("Producto desconocido"),
        }

        if not product:
            result["valid"] = False
            result["error_type"] = "missing"
            result["error_message"] = _("Línea sin producto")
            return result

        # Check product's CABYS code
        cabys_code = None
        if product.cabys_code:
            cabys_code = product.cabys_code
        elif product.categ_id and product.categ_id.cabys_code:
            cabys_code = product.categ_id.cabys_code

        if not cabys_code:
            result["valid"] = False
            result["error_type"] = "missing"
            result["error_message"] = _("Producto sin código CABYS: %s") % product.name
            return result

        result["cabys_code"] = cabys_code

        # If partner has exoneration, validate CABYS is in allowed list
        if partner and partner.has_exoneration:
            if partner.allowed_cabys_ids:
                allowed_codes = [code.name for code in partner.allowed_cabys_ids]
                if cabys_code not in allowed_codes:
                    result["valid"] = False
                    result["error_type"] = "not_approved"
                    result["error_message"] = _(
                        "El código CABYS %s del producto '%s' no está aprobado para exoneración"
                    ) % (cabys_code, product.name)

        return result

    @api.model
    def validate_cabys_for_lines(self, lines, partner=None):
        """
        Validate CABYS codes for multiple product lines.

        Args:
            lines: List of line records (account.move.line or pos.order.line)
                   Each line should have 'product_id' attribute
            partner: Optional res.partner record

        Returns:
            tuple: (is_valid: bool, errors: list of error dicts)
        """
        errors = []

        for line in lines:
            # Skip non-product lines
            if hasattr(line, "display_type") and line.display_type != "product":
                continue

            # Get product - handle both account.move.line and pos.order.line
            product = None
            if hasattr(line, "product_id"):
                product = line.product_id

            if not product:
                continue

            # Skip "IVA Devuelto" and "Otros Cargos" products
            if product.name == "IVA Devuelto":
                continue
            if product.categ_id and product.categ_id.name == "Otros Cargos":
                continue

            result = self.validate_cabys_for_line(product, partner)
            if not result["valid"]:
                errors.append(result)

        is_valid = len(errors) == 0
        return is_valid, errors

    @api.model
    def format_cabys_validation_error(self, tipo_documento, errors):
        """
        Format CABYS validation error message.

        Args:
            tipo_documento: Document type code
            errors: List of error dicts from validate_cabys_for_lines

        Returns:
            str: Formatted error message
        """
        doc_type_labels = self.get_fe_doc_type_labels()
        doc_label = doc_type_labels.get(tipo_documento, tipo_documento)

        # Group errors by type
        missing_cabys = [e for e in errors if e["error_type"] == "missing"]
        not_approved = [e for e in errors if e["error_type"] == "not_approved"]

        error_parts = []

        if missing_cabys:
            products_list = "\n  • " + "\n  • ".join(
                [e["product_name"] for e in missing_cabys]
            )
            error_parts.append(
                _("Los siguientes productos no tienen código CABYS asignado:%s")
                % products_list
            )

        if not_approved:
            products_list = "\n  • " + "\n  • ".join(
                [
                    f"{e['product_name']} (CABYS: {e['cabys_code']})"
                    for e in not_approved
                ]
            )
            error_parts.append(
                _("Los siguientes códigos CABYS no están aprobados para exoneración:%s")
                % products_list
            )

        error_details = "\n\n".join(error_parts)

        return _(
            "⚠️ No se puede generar el documento electrónico (%s).\n\n"
            "%s\n\n"
            "Por favor asigne los códigos CABYS correspondientes a los productos antes de continuar."
        ) % (doc_label, error_details)

    @api.model
    def raise_cabys_validation_error(self, tipo_documento, errors):
        """
        Raise a UserError with a clear message about missing/invalid CABYS codes.

        Args:
            tipo_documento: Document type code
            errors: List of error dicts from validate_cabys_for_lines
        """
        error_message = self.format_cabys_validation_error(tipo_documento, errors)
        raise UserError(error_message)

    # =========================================================================
    # COMBINED VALIDATION (Shared)
    # =========================================================================

    @api.model
    def should_validate_for_fe(self, tipo_documento, company):
        """
        Determine if FE validation should be applied based on document type and company settings.

        Args:
            tipo_documento: Document type code
            company: res.company record

        Returns:
            bool: True if validation should be applied
        """
        if not company:
            company = self.env.company

        # Check if electronic invoicing is enabled
        if not company.invoice_is_electronic:
            return False

        # Check if FE environment is disabled
        if (
            hasattr(company, "frm_ws_ambiente")
            and company.frm_ws_ambiente == "disabled"
        ):
            return False

        return True

    @api.model
    def validate_fe_data(
        self, tipo_documento, partner, lines, reference_document=None, company=None
    ):
        """
        Combined validation for FE: client + CABYS.

        This is the main entry point for validating all FE requirements.

        Args:
            tipo_documento: Document type code
            partner: res.partner record
            lines: Product lines to validate
            reference_document: Optional reference document for NC
            company: Optional company record

        Returns:
            dict: {
                'valid': bool,
                'partner_valid': bool,
                'partner_missing_fields': list,
                'cabys_valid': bool,
                'cabys_errors': list,
                'error_message': str (combined error message if invalid)
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

        if not self.should_validate_for_fe(tipo_documento, company):
            return result

        error_messages = []

        # Validate partner (only for FE, NC, ND, FEE - not TE)
        if tipo_documento in ("FE", "NC", "ND", "FEE"):
            partner_valid, missing_fields = self.validate_partner_for_fe(
                partner, tipo_documento, reference_document
            )
            result["partner_valid"] = partner_valid
            result["partner_missing_fields"] = missing_fields

            if not partner_valid:
                result["valid"] = False
                error_messages.append(
                    self.format_partner_validation_error(
                        partner, tipo_documento, missing_fields
                    )
                )

        # Validate CABYS for all document types that require it
        cabys_valid, cabys_errors = self.validate_cabys_for_lines(lines, partner)
        result["cabys_valid"] = cabys_valid
        result["cabys_errors"] = cabys_errors

        if not cabys_valid:
            result["valid"] = False
            error_messages.append(
                self.format_cabys_validation_error(tipo_documento, cabys_errors)
            )

        if error_messages:
            result["error_message"] = "\n\n" + "─" * 50 + "\n\n".join(error_messages)

        return result

    @api.model
    def raise_fe_validation_error(self, validation_result):
        """
        Raise UserError if validation failed.

        Args:
            validation_result: dict from validate_fe_data
        """
        if not validation_result["valid"]:
            raise UserError(validation_result["error_message"])
