# -*- coding: utf-8 -*-

"""Installation helpers for the unified Costa Rican localization."""

from odoo import Command

from .components.cabys.catalog_loader import load_bundled_catalog


_SEQUENCE_SPECS = {
    "FE_sequence_id": ("sequence.FE", "Secuencia de Factura Electrónica"),
    "TE_sequence_id": ("sequence.TE", "Secuencia de Tiquete Electrónico"),
    "FEE_sequence_id": ("sequence.FEE", "Secuencia de Factura Electrónica de Exportación"),
    "NC_sequence_id": ("sequence.NC", "Secuencia de Nota Crédito Electrónica"),
    "ND_sequence_id": ("sequence.ND", "Secuencia de Nota Débito Electrónica"),
    "FEC_sequence_id": ("sequence.FEC", "Secuencia de Factura Electrónica de Compra"),
    "REP_sequence_id": ("sequence.REP", "Secuencia de Recibo Electrónico de Pago"),
}


def _company_sequences(env, company):
    Sequence = env["ir.sequence"].sudo().with_company(company)
    sequences = {}
    for field_name, (code, name) in _SEQUENCE_SPECS.items():
        sequence = Sequence.search(
            [("code", "=", code), ("company_id", "=", company.id)], limit=1
        )
        if not sequence:
            sequence = Sequence.create(
                {
                    "name": name,
                    "code": code,
                    "padding": 10,
                    "company_id": company.id,
                }
            )
        sequences[field_name] = sequence
    return sequences


def _configure_journals(env, company, sequences):
    journals = env["account.journal"].sudo().search([("company_id", "=", company.id)])
    sale_values = {
        field_name: sequences[field_name].id
        for field_name in (
            "FE_sequence_id",
            "TE_sequence_id",
            "FEE_sequence_id",
            "NC_sequence_id",
            "ND_sequence_id",
            "REP_sequence_id",
        )
    }
    purchase_values = {"FEC_sequence_id": sequences["FEC_sequence_id"].id}
    for journal in journals:
        wanted = sale_values if journal.type == "sale" else purchase_values if journal.type == "purchase" else {}
        values = {
            field_name: value
            for field_name, value in wanted.items()
            if not journal[field_name]
        }
        if values:
            journal.write(values)
    if not company.FEC_sequence_id:
        company.FEC_sequence_id = sequences["FEC_sequence_id"]
    company.try_create_configuration_sequences()


def _ticofac_default_tax(env, company, tax_use):
    return env["account.tax"].sudo().search(
        [
            ("company_id", "=", company.id),
            ("tax_code", "=", "01"),
            ("amount", "=", 13.0),
            ("type_tax_use", "=", tax_use),
            ("non_tax_deductible", "=", False),
        ],
        limit=1,
    )


def _standard_odoo_taxes(env, company):
    model_data = env["ir.model.data"].sudo().search(
        [("module", "=", "account"), ("model", "=", "account.tax")]
    )
    return env["account.tax"].sudo().browse(model_data.mapped("res_id")).exists().filtered(
        lambda tax: tax.company_id == company
    )


def _configure_taxes(env, company):
    sale_tax = _ticofac_default_tax(env, company, "sale")
    purchase_tax = _ticofac_default_tax(env, company, "purchase")
    standard_taxes = _standard_odoo_taxes(env, company)

    if sale_tax:
        company.account_sale_tax_id = sale_tax
    if purchase_tax:
        company.account_purchase_tax_id = purchase_tax

    products = env["product.template"].sudo().with_company(company).search([])
    standard_sale = standard_taxes.filtered(lambda tax: tax.type_tax_use in ("sale", "all"))
    standard_purchase = standard_taxes.filtered(lambda tax: tax.type_tax_use in ("purchase", "all"))
    for product in products:
        sale_to_remove = product.taxes_id & standard_sale
        purchase_to_remove = product.supplier_taxes_id & standard_purchase
        if sale_to_remove:
            commands = [Command.unlink(tax.id) for tax in sale_to_remove]
            if sale_tax:
                commands.append(Command.link(sale_tax.id))
            product.taxes_id = commands
        if purchase_to_remove:
            commands = [Command.unlink(tax.id) for tax in purchase_to_remove]
            if purchase_tax:
                commands.append(Command.link(purchase_tax.id))
            product.supplier_taxes_id = commands

    if standard_taxes:
        standard_taxes.write({"active": False})


def configure_decimal_precision(env):
    env["decimal.precision"].sudo().search(
        [("name", "in", ("Product Price", "Discount", "account"))]
    ).write({"digits": 2})


def configure_ticofac_accounting(env):
    for company in env["res.company"].sudo().search([]):
        sequences = _company_sequences(env, company)
        _configure_journals(env, company, sequences)
        _configure_taxes(env, company)


def configure_pos_payment_methods(env):
    env["pos.payment.method"].sudo().search(
        [("account_payment_method_id", "=", False)]
    )._ticofac_assign_hacienda_payment_method()


def post_init_hook(env):
    """Prepare a fresh database without manual fiscal configuration."""
    load_bundled_catalog(env)
    configure_decimal_precision(env)
    configure_ticofac_accounting(env)
    configure_pos_payment_methods(env)
