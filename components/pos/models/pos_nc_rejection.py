# -*- coding: utf-8 -*-
"""Neutralize the operational effects of POS credit notes rejected by Hacienda."""

import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _ticofac_neutralize_rejected_nc(self):
        """Create auditable counter-movements for a rejected POS credit note.

        Idempotency uses Odoo's standard reversal links: ``reversed_entry_id``
        for accounting and ``return_id`` for inventory. No business record is
        deleted and no custom database column is required.
        """
        for order in self:
            invoice = order.account_move
            if (
                not invoice
                or invoice.tipo_documento != "NC"
                or invoice.state_tributacion != "rechazado"
            ):
                continue

            account_reversals = self.env["account.move"]
            stock_returns = self.env["stock.picking"]

            # Neutralize the accounting effect of the rejected credit note.
            invoice_reversals = invoice.reversal_move_ids.filtered(
                lambda move: move.ref
                and move.ref.startswith("Neutralización interna de NC rechazada")
            )
            if invoice_reversals:
                account_reversals |= invoice_reversals
            elif invoice.state == "posted":
                account_reversals |= invoice.with_context(
                    ticofac_internal_nc_neutralization=True
                )._reverse_moves(
                    [
                        {
                            "ref": _("Neutralización interna de NC rechazada %s")
                            % invoice.name,
                            "tipo_documento": "disabled",
                            "number_electronic": False,
                            "sequence": False,
                            "state_tributacion": "na",
                        }
                    ],
                    cancel=True,
                )

            # Neutralize the POS refund payment. Never reverse a shared move,
            # because it may contain money belonging to other POS orders.
            payment_moves = order.payment_ids.mapped("account_move_id").filtered(
                lambda move: move.state == "posted"
            )
            for payment_move in payment_moves:
                linked_payments = self.env["pos.payment"].search(
                    [("account_move_id", "=", payment_move.id)]
                )
                if linked_payments.mapped("pos_order_id") - order:
                    raise UserError(
                        _(
                            "No se puede neutralizar automáticamente la NC %s: "
                            "el movimiento de pago %s contiene otros pedidos."
                        )
                        % (invoice.name, payment_move.name)
                    )
                existing_reversals = payment_move.reversal_move_ids.filtered(
                    lambda move: move.ref
                    and move.ref.startswith("Reversión de reembolso por NC rechazada")
                )
                if existing_reversals:
                    account_reversals |= existing_reversals
                else:
                    account_reversals |= payment_move.with_context(
                        ticofac_internal_nc_neutralization=True
                    )._reverse_moves(
                        [
                            {
                                "ref": _(
                                    "Reversión de reembolso por NC rechazada %s"
                                )
                                % invoice.name
                            }
                        ],
                        cancel=True,
                    )

            # Reverse every completed stock operation created by this refund.
            original_pickings = order.picking_ids.filtered(
                lambda picking: picking.state == "done" and not picking.return_id
            )
            for picking in original_pickings:
                existing_returns = self.env["stock.picking"].search(
                    [("return_id", "=", picking.id), ("state", "!=", "cancel")]
                )
                if existing_returns:
                    stock_returns |= existing_returns
                    continue
                wizard = self.env["stock.return.picking"].with_context(
                    active_model="stock.picking",
                    active_id=picking.id,
                    active_ids=[picking.id],
                ).create({"picking_id": picking.id})
                action = wizard.action_create_returns_all()
                return_picking = self.env["stock.picking"].browse(action["res_id"])
                validation_result = return_picking.with_context(skip_sms=True).button_validate()
                if isinstance(validation_result, dict):
                    raise UserError(
                        _(
                            "La devolución de inventario %s requiere intervención manual."
                        )
                        % return_picking.display_name
                    )
                stock_returns |= return_picking

            invoice.message_post(
                body=_(
                    "NC rechazada por Hacienda neutralizada automáticamente. "
                    "Contramovimientos contables: %s. Inventario: %s."
                )
                % (
                    ", ".join(account_reversals.mapped("name")) or _("ninguno"),
                    ", ".join(stock_returns.mapped("name")) or _("ninguno"),
                )
            )
            _logger.warning(
                "Rejected POS NC %s neutralized for order %s",
                invoice.name,
                order.name,
            )


class AccountMove(models.Model):
    _inherit = "account.move"

    def write(self, vals):
        result = super().write(vals)
        if (
            vals.get("state_tributacion") == "rechazado"
            and not self.env.context.get("ticofac_internal_nc_neutralization")
        ):
            rejected_nc = self.filtered(
                lambda move: move.tipo_documento == "NC"
                and move.move_type == "out_refund"
            )
            orders = self.env["pos.order"].search(
                [("account_move", "in", rejected_nc.ids)]
            )
            orders._ticofac_neutralize_rejected_nc()
        return result
