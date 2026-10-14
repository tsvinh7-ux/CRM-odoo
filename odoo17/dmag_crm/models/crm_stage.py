from odoo import fields, models


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    dmag_required_field_ids = fields.Many2many(
        'ir.model.fields', 'dmag_crm_stage_required_field_rel', 'stage_id', 'field_id',
        string='Điều kiện để vào giai đoạn',
        domain=[('model', '=', 'crm.lead')],
        help='Cơ hội chỉ được chuyển vào giai đoạn này khi các trường này đã có giá trị (cổng giai đoạn).')
