from odoo import fields, models

PIPELINE_SELECTION = [
    ('diagnosis', 'P1 · Chẩn đoán'),
    ('prescription', 'P2 · Lộ trình module'),
    ('edu', 'P3 · EDU giao dịch'),
    ('tech', 'P4 · TECH'),
    ('alliance', 'P5 · Liên minh (để sau)'),
]


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    dmag_pipeline_type = fields.Selection(PIPELINE_SELECTION, string='Loại pipeline DMAG')
