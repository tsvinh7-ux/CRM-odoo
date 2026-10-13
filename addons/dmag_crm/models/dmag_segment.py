from odoo import api, fields, models

STAGE_G_SELECTION = [
    ('g0', 'G0 · Ươm tạo'),
    ('g1', 'G1 · Bắt bệnh'),
    ('g2', 'G2 · Khóa móng'),
    ('g3', 'G3 · Setup 90 ngày'),
    ('g4', 'G4 · Liên minh'),
    ('g5', 'G5 · Vốn hóa'),
]

# Hình thức triển khai của một module, xếp theo mức độ can thiệp tăng dần.
TIER_SELECTION = [
    ('self', 'Tự học'),
    ('guided', 'Học có hướng dẫn'),
    ('one_on_one', 'Kèm 1:1'),
    ('field', 'Triển khai thực địa'),
]
TIER_ORDER = [code for code, _label in TIER_SELECTION]

DISC_SELECTION = [
    ('d', 'D · Thủ lĩnh'),
    ('i', 'I · Ảnh hưởng'),
    ('s', 'S · Kiên định'),
    ('c', 'C · Tuân thủ'),
]


class DmagSegment(models.Model):
    _name = 'dmag.segment'
    _description = 'Phân khúc phòng khám (PK)'
    _order = 'sequence, id'

    name = fields.Char('Tên phân khúc', required=True, translate=True)
    code = fields.Char('Mã', required=True, help='Ví dụ: PK1 … PK5')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    score_min = fields.Float('Điểm DDA từ', help='Bao gồm giá trị này')
    score_max = fields.Float('Điểm DDA đến', help='Không bao gồm giá trị này. Để 0 nếu không giới hạn trên.')
    revenue_min = fields.Float('Doanh thu/tháng từ (triệu)')
    revenue_max = fields.Float('Doanh thu/tháng đến (triệu)', help='Để 0 nếu không giới hạn trên.')
    chair_min = fields.Integer('Số ghế từ')
    chair_max = fields.Integer('Số ghế đến')
    stage_g = fields.Selection(STAGE_G_SELECTION, string='Chặng tương ứng')
    flow = fields.Integer('Luồng', help='Luồng 2–6 theo khung phân loại DDA')
    allow_self = fields.Boolean('Được bán: Tự học', default=True)
    allow_guided = fields.Boolean('Được bán: Học có hướng dẫn', default=True)
    allow_one_on_one = fields.Boolean('Được bán: Kèm 1:1', default=True)
    allow_field = fields.Boolean('Được bán: Triển khai thực địa', default=True)
    is_focus = fields.Boolean('Phân khúc trọng tâm')
    channel_note = fields.Text('Kênh tiếp cận')
    description = fields.Text('Đặc điểm')
    partner_count = fields.Integer('Số phòng khám', compute='_compute_partner_count')

    _code_uniq = models.Constraint('unique(code)', 'Mã phân khúc phải là duy nhất.')

    def _compute_partner_count(self):
        groups = self.env['res.partner']._read_group(
            [('dmag_segment_id', 'in', self.ids)], ['dmag_segment_id'], ['__count'])
        counts = {segment.id: count for segment, count in groups}
        for segment in self:
            segment.partner_count = counts.get(segment.id, 0)

    def _allowed_tiers(self):
        self.ensure_one()
        return [tier for tier in TIER_ORDER if self[f'allow_{tier}']]

    @api.model
    def _find_by_score(self, score):
        for segment in self.search([]):
            if score >= segment.score_min and (not segment.score_max or score < segment.score_max):
                return segment
        return self.browse()

    @api.model
    def _find_by_revenue(self, revenue):
        """Ước tính sơ bộ khi chưa có DDA, dựa trên doanh thu/tháng (triệu đồng)."""
        if not revenue:
            return self.browse()
        for segment in self.search([]):
            if revenue >= segment.revenue_min and (not segment.revenue_max or revenue < segment.revenue_max):
                return segment
        return self.browse()

    def action_view_partners(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('dmag_segment_id', '=', self.id)],
        }

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for segment in self:
            segment.display_name = f'{segment.code} · {segment.name}' if segment.code else segment.name
