
from odoo import models, fields


class ReferenceDocument(models.Model):
    _name = "reference.document"
    _description = "Electronic Invoice Reference Document"

    active = fields.Boolean(
        default=True
    )
    code = fields.Char()
    name = fields.Char()
