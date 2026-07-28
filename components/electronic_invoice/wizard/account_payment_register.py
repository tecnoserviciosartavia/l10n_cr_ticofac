from odoo.exceptions import UserError

from odoo import _, api, fields, models


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    generate_rep = fields.Boolean(
        string="Generate Electronic Payment Receipt (REP)",
        default=False,
        help="Check this box to generate a Recibo Electrónico de Pago (REP) upon payment creation.",
    )

    show_rep_option = fields.Boolean(compute="_compute_show_rep_option", store=False)

    rep_unavailable_message = fields.Char(
        string="REP Unavailable", compute="_compute_show_rep_option", store=False
    )

    # Store linked invoices for REP generation context
    rep_invoice_ids = fields.Many2many(
        "account.move",
        string="REP Source Invoices",
        compute="_compute_rep_invoice_ids",
        store=False,
    )

    @api.depends("line_ids")
    def _compute_rep_invoice_ids(self):
        """Compute the invoices that will be linked to the REP."""
        for wizard in self:
            moves = wizard.line_ids.move_id
            # Filter to customer invoices only (out_invoice)
            customer_invoices = moves.filtered(lambda m: m.move_type == "out_invoice")
            wizard.rep_invoice_ids = customer_invoices

    @api.depends("line_ids", "company_id")
    def _compute_show_rep_option(self):
        """
        Compute whether REP option should be shown.
        REP is allowed ONLY if ALL of the following are met:
        1. All invoices were successfully issued as electronic documents (state_tributacion='aceptado')
        2. All invoices have Sale Condition = Crédito (02) or Servicios prestados al Estado a Crédito (08)
        3. Company has electronic invoicing enabled (frm_ws_ambiente != 'disabled')
        4. REP sequence is configured on the sales journal
        """
        allowed_conditions = ["02", "08"]

        for wizard in self:
            moves = wizard.line_ids.move_id
            customer_invoices = moves.filtered(lambda m: m.move_type == "out_invoice")

            # Must have at least one customer invoice
            if not customer_invoices:
                wizard.show_rep_option = False
                wizard.rep_unavailable_message = False
                continue

            # Check company configuration
            company = wizard.company_id
            if not company or company.frm_ws_ambiente == "disabled":
                wizard.show_rep_option = False
                wizard.rep_unavailable_message = _(
                    "Electronic invoicing is disabled for this company."
                )
                continue

            # Check all invoices meet REP requirements
            invalid_reasons = []

            for inv in customer_invoices:
                # Check electronic invoice status
                if inv.state_tributacion != "aceptado":
                    invalid_reasons.append(
                        _("Invoice is not accepted by Hacienda (status: %s).")
                        % (inv.state_tributacion or "N/A")
                    )
                    continue

                # Check electronic key exists
                if not inv.number_electronic or len(inv.number_electronic) != 50:
                    invalid_reasons.append(
                        "Invoice does not have a valid electronic key."
                    )
                    continue

                # Check sale condition
                sale_cond_code = (
                    inv.invoice_payment_term_id.sale_conditions_id.code
                    if inv.invoice_payment_term_id
                    and inv.invoice_payment_term_id.sale_conditions_id
                    else False
                )
                if sale_cond_code not in allowed_conditions:
                    invalid_reasons.append(
                        _(
                            "Invoice has sale condition '%s'. REP requires 'Crédito (02)' or 'Servicios prestados al Estado a Crédito (08)'."
                        )
                        % (sale_cond_code or "N/A")
                    )
                    continue

                # Check REP sequence on sales journal
                if not inv.journal_id.REP_sequence_id:
                    invalid_reasons.append(
                        _("Sales Journal '%s' does not have REP sequence configured.")
                        % inv.journal_id.name
                    )
                    continue

            if invalid_reasons:
                wizard.show_rep_option = False
                wizard.rep_unavailable_message = invalid_reasons[0]  # Show first reason
            else:
                wizard.show_rep_option = True
                wizard.rep_unavailable_message = False

    def _create_payment_vals_from_wizard(self, batch_result):
        """Override to add REP-related values to payment creation."""
        vals = super()._create_payment_vals_from_wizard(batch_result)

        if self.generate_rep and self.show_rep_option:
            vals["generate_rep"] = True
            # Store all valid invoice IDs for REP generation
            valid_invoices = self.rep_invoice_ids.filtered(
                lambda m: m.state_tributacion == "aceptado" and m.number_electronic
            )
            if valid_invoices:
                vals["rep_bak_invoice_id"] = valid_invoices[0].id
                # Store all invoice IDs in context for multi-invoice REP
                vals["rep_all_invoice_ids"] = valid_invoices.ids

        return vals

    def _create_payments(self):
        """Override to validate REP prerequisites before payment creation."""
        if self.generate_rep:
            if not self.show_rep_option:
                raise UserError(
                    _("Cannot generate REP: %s")
                    % (self.rep_unavailable_message or _("Requirements not met."))
                )

            # Additional blocking validation before payment creation
            self._validate_rep_prerequisites_blocking()

        payments = super()._create_payments()

        # Link invoice IDs to payments for REP context (before reconciliation)
        if self.generate_rep and payments:
            valid_invoices = self.rep_invoice_ids.filtered(
                lambda m: m.state_tributacion == "aceptado" and m.number_electronic
            )
            if valid_invoices:
                for payment in payments:
                    payment.write(
                        {
                            "generate_rep": True,
                            "rep_bak_invoice_id": valid_invoices[0].id,
                        }
                    )
                    # Store all invoice IDs for multi-reference REP
                    payment.rep_all_invoice_ids = [(6, 0, valid_invoices.ids)]

        return payments

    def _validate_rep_prerequisites_blocking(self):
        """
        Validate all prerequisites for REP generation.
        This is called BEFORE payment creation to fail fast.
        """
        self.ensure_one()
        company = self.company_id

        # Company Configuration
        if company.frm_ws_ambiente == "disabled":
            raise UserError(_("Electronic Invoicing is disabled for this company."))

        if not company.signature:
            raise UserError(
                _(
                    "Electronic Invoice cryptographic key (P12 certificate) is not configured in Company settings."
                )
            )

        if not company.frm_pin:
            raise UserError(
                _("Electronic Invoice PIN is not configured in Company settings.")
            )

        if not company.frm_ws_identificador or not company.frm_ws_password:
            raise UserError(
                _(
                    "Hacienda credentials (user/password) are not configured in Company settings."
                )
            )

        # Invoice validations
        valid_invoices = self.rep_invoice_ids.filtered(
            lambda m: m.state_tributacion == "aceptado" and m.number_electronic
        )

        if not valid_invoices:
            raise UserError(_("No valid electronic invoices found for REP generation."))

        # Check REP sequence on first invoice's journal
        main_invoice = valid_invoices[0]
        if not main_invoice.journal_id.REP_sequence_id:
            raise UserError(
                _(
                    "The Sales Journal '%s' does not have a REP sequence configured. "
                    "Please configure it in Accounting > Configuration > Journals."
                )
                % main_invoice.journal_id.name
            )
