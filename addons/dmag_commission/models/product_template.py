from odoo import api, fields, models

COMMISSION_GROUP_SELECTION = [
    ('book_event', 'Sách, ấn phẩm, vé sự kiện'),
    ('club', 'DME Club (hội viên)'),
    ('dda_deposit', 'Cọc DDA'),
    ('module_learning', 'Module – Tự học / Có hướng dẫn'),
    ('module_one_on_one', 'Module – Kèm 1:1'),
    ('module_field', 'Module – Thực địa / gói Setup'),
    ('tech_new', 'TECH – năm đầu'),
    ('tech_renew', 'TECH – gia hạn'),
    ('other', 'Khác'),
]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    dmag_commission_group = fields.Selection(
        COMMISSION_GROUP_SELECTION, string='Nhóm hoa hồng',
        compute='_compute_dmag_commission_group', store=True, readonly=False,
        help='Quyết định tỷ lệ hoa hồng áp dụng cho sản phẩm này.')

    @api.depends('dmag_is_dda_deposit', 'dmag_tier')
    def _compute_dmag_commission_group(self):
        mapping = {'self': 'module_learning', 'guided': 'module_learning',
                   'one_on_one': 'module_one_on_one', 'field': 'module_field'}
        for template in self:
            if template.dmag_is_dda_deposit:
                template.dmag_commission_group = 'dda_deposit'
            elif template.dmag_tier:
                template.dmag_commission_group = mapping[template.dmag_tier]
            elif not template.dmag_commission_group:
                template.dmag_commission_group = 'other'
