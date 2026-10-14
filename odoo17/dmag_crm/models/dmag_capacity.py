from datetime import date

from odoo import api, fields, models

QUARTER_SELECTION = [('1', 'Quý 1'), ('2', 'Quý 2'), ('3', 'Quý 3'), ('4', 'Quý 4')]


def quarter_bounds(year, quarter):
    start = date(year, 3 * (quarter - 1) + 1, 1)
    end = date(year + 1, 1, 1) if quarter == 4 else date(year, 3 * quarter + 1, 1)
    return start, end


class DmagCapacity(models.Model):
    """Chỉ tiêu suất triển khai thực địa theo quý.

    Hệ thống chỉ đếm và cảnh báo; việc chốt vượt suất do quản lý duyệt tay.
    """
    _name = 'dmag.capacity'
    _description = 'Suất triển khai theo quý'
    _order = 'year desc, quarter desc'

    name = fields.Char(compute='_compute_name', store=True)
    year = fields.Integer('Năm', required=True, default=lambda self: fields.Date.today().year)
    quarter = fields.Selection(QUARTER_SELECTION, string='Quý', required=True,
                               default=lambda self: str((fields.Date.today().month - 1) // 3 + 1))
    slots_total = fields.Integer('Tổng suất', default=3)
    slots_used = fields.Integer('Đã dùng', compute='_compute_slots')
    slots_left = fields.Integer('Còn lại', compute='_compute_slots')
    note = fields.Text('Ghi chú')

    _sql_constraints = [
        ('period_uniq', 'unique(year, quarter)', 'Mỗi quý chỉ có một chỉ tiêu suất.'),
    ]

    @api.depends('year', 'quarter')
    def _compute_name(self):
        for rec in self:
            rec.name = f'Q{rec.quarter}/{rec.year}'

    def _won_leads_domain(self):
        self.ensure_one()
        start, end = quarter_bounds(self.year, int(self.quarter))
        return [
            ('dmag_uses_capacity', '=', True),
            ('stage_id.is_won', '=', True),
            ('date_closed', '>=', fields.Datetime.to_datetime(start)),
            ('date_closed', '<', fields.Datetime.to_datetime(end)),
        ]

    @api.depends('year', 'quarter', 'slots_total')
    def _compute_slots(self):
        Lead = self.env['crm.lead'].with_context(active_test=False)
        for rec in self:
            rec.slots_used = Lead.search_count(rec._won_leads_domain()) if rec.year and rec.quarter else 0
            rec.slots_left = rec.slots_total - rec.slots_used

    @api.model
    def _for_date(self, day):
        day = fields.Date.to_date(day) or fields.Date.today()
        return self.search([('year', '=', day.year), ('quarter', '=', str((day.month - 1) // 3 + 1))], limit=1)

    def action_view_leads(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Cơ hội dùng suất {self.name}',
            'res_model': 'crm.lead',
            'view_mode': 'tree,form',
            'domain': self._won_leads_domain(),
            'context': {'active_test': False},
        }
