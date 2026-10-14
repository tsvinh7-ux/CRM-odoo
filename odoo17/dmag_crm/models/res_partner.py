import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .dmag_segment import DISC_SELECTION, STAGE_G_SELECTION

LIFECYCLE_SELECTION = [
    ('follower', 'Người theo dõi'),
    ('mql', 'MQL'),
    ('sql', 'SQL'),
    ('diagnosed', 'Đã chẩn đoán (có DDA)'),
    ('customer', 'Khách hàng'),
    ('active', 'Khách hàng hoạt động'),
    ('paused', 'Tạm dừng'),
    ('churned', 'Rời bỏ'),
]


def normalize_vn_phone(phone):
    """Chuẩn hoá SĐT Việt Nam về dạng 0xxxxxxxxx để chống trùng.

    Chấp nhận '+84 965…', '84965…', '0973. 232.598', '965…' (thiếu số 0 đầu).
    Ô chứa nhiều số (ngăn cách bằng / , ;) chỉ lấy số đầu tiên.
    """
    if not phone:
        return False
    first = re.split(r'[/,;]', phone)[0]
    digits = re.sub(r'\D', '', first)
    if digits.startswith('84') and len(digits) in (11, 12):
        digits = '0' + digits[2:]
    elif len(digits) == 9 and not digits.startswith('0'):
        digits = '0' + digits
    return digits or False


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # --- Hồ sơ phòng khám (cấp công ty) ---
    dmag_is_clinic = fields.Boolean('Là phòng khám', help='Đánh dấu hồ sơ phòng khám nha khoa (khách hàng B2B).')
    dmag_segment_id = fields.Many2one('dmag.segment', string='Phân khúc', tracking=True, index=True)
    dmag_segment_override = fields.Boolean('Ghi đè phân khúc',
                                           help='Bật khi chuyên viên xếp phân khúc tay, khác với kết quả DDA.')
    dmag_segment_reason = fields.Char('Lý do ghi đè')
    dmag_stage_g = fields.Selection(STAGE_G_SELECTION, string='Chặng', tracking=True)
    dmag_flow = fields.Integer(related='dmag_segment_id.flow', string='Luồng')
    dmag_lifecycle = fields.Selection(LIFECYCLE_SELECTION, string='Vòng đời', default='follower', tracking=True)
    dmag_account_owner_id = fields.Many2one('res.users', string='Account Owner', tracking=True,
                                            domain=[('share', '=', False)])
    dmag_dda_score = fields.Float('Điểm DDA gần nhất', readonly=True, tracking=True)
    dmag_dda_date = fields.Date('Ngày DDA gần nhất', readonly=True)
    dmag_t1_redflag = fields.Boolean('Cờ đỏ T1 (pháp lý)', readonly=True, tracking=True)
    dmag_chair_count = fields.Integer('Số ghế')
    dmag_branch_count = fields.Integer('Số cơ sở', default=1)
    dmag_doctor_count = fields.Integer('Số bác sĩ')
    dmag_staff_count = fields.Integer('Số nhân sự')
    dmag_monthly_revenue = fields.Float('Doanh thu/tháng (triệu)')
    dmag_revenue_per_chair = fields.Float('Hiệu suất/ghế (triệu)', compute='_compute_revenue_per_chair')
    dmag_owner_revenue_pct = fields.Float('% doanh số do chủ tạo')
    dmag_owner_chair_hours = fields.Float('Giờ ngồi ghế của chủ/tuần')
    dmag_specialty = fields.Selection([
        ('general', 'Tổng quát'),
        ('ortho', 'Chỉnh nha'),
        ('implant', 'Implant'),
        ('aesthetic', 'Thẩm mỹ'),
        ('kids', 'Nha khoa trẻ em'),
        ('multi', 'Đa chuyên khoa'),
    ], string='Chuyên môn chính')
    dmag_software = fields.Char('Phần mềm đang dùng')
    dmag_hub = fields.Char('Hub tỉnh')
    dmag_decision_disc = fields.Selection(DISC_SELECTION, string='DISC người quyết định',
                                          compute='_compute_decision_disc')
    dmag_suggested_segment_id = fields.Many2one('dmag.segment', string='Phân khúc gợi ý',
                                                compute='_compute_suggested_segment')

    # --- Người liên hệ (cấp cá nhân) ---
    dmag_disc = fields.Selection(DISC_SELECTION, string='DISC')
    dmag_buying_role = fields.Selection([
        ('decision', 'Người quyết định'),
        ('influencer', 'Người ảnh hưởng'),
        ('user', 'Người sử dụng'),
        ('blocker', 'Người cản'),
        ('payer', 'Người thanh toán'),
    ], string='Vai trò mua hàng')
    dmag_owner_type = fields.Selection([
        ('owner_doctor', 'Chủ kiêm bác sĩ'),
        ('owner_investor', 'Chủ không trực tiếp điều trị'),
        ('manager', 'Quản lý / Giám đốc điều hành'),
        ('medical_director', 'Giám đốc chuyên môn'),
        ('head', 'Trưởng bộ phận'),
        ('frontline', 'Tuyến đầu'),
    ], string='Vị trí')
    dmag_consent = fields.Boolean('Đồng ý nhận thông tin')
    dmag_consent_date = fields.Date('Ngày đồng ý')

    dmag_phone_key = fields.Char('SĐT chuẩn hoá', compute='_compute_phone_key', store=True, index=True)

    @api.depends('phone')
    def _compute_phone_key(self):
        for partner in self:
            partner.dmag_phone_key = normalize_vn_phone(partner.phone)

    @api.depends('dmag_monthly_revenue', 'dmag_chair_count')
    def _compute_revenue_per_chair(self):
        for partner in self:
            partner.dmag_revenue_per_chair = (
                partner.dmag_monthly_revenue / partner.dmag_chair_count if partner.dmag_chair_count else 0.0)

    @api.depends('child_ids.dmag_buying_role', 'child_ids.dmag_disc')
    def _compute_decision_disc(self):
        for partner in self:
            decision = partner.child_ids.filtered(lambda c: c.dmag_buying_role == 'decision' and c.dmag_disc)[:1]
            partner.dmag_decision_disc = decision.dmag_disc or False

    @api.depends('dmag_dda_score', 'dmag_dda_date', 'dmag_monthly_revenue')
    def _compute_suggested_segment(self):
        Segment = self.env['dmag.segment']
        for partner in self:
            if partner.dmag_dda_date:
                partner.dmag_suggested_segment_id = Segment._find_by_score(partner.dmag_dda_score)
            else:
                partner.dmag_suggested_segment_id = Segment._find_by_revenue(partner.dmag_monthly_revenue)

    @api.constrains('dmag_phone_key', 'dmag_is_clinic')
    def _check_dmag_duplicate_clinic(self):
        for partner in self.filtered(lambda p: p.dmag_is_clinic and p.dmag_phone_key):
            duplicate = self.search([
                ('id', '!=', partner.id),
                ('dmag_is_clinic', '=', True),
                ('dmag_phone_key', '=', partner.dmag_phone_key),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Số điện thoại %(phone)s đã thuộc phòng khám "%(clinic)s". '
                    'Hãy mở hồ sơ đó thay vì tạo mới (mỗi phòng khám chỉ có một hồ sơ).',
                    phone=partner.phone, clinic=duplicate.display_name))

    @api.constrains('dmag_segment_override', 'dmag_segment_reason')
    def _check_segment_override_reason(self):
        for partner in self:
            if partner.dmag_segment_override and not partner.dmag_segment_reason:
                raise ValidationError(_('Ghi đè phân khúc phải có lý do.'))

    def action_dmag_apply_suggested_segment(self):
        for partner in self:
            if partner.dmag_suggested_segment_id:
                partner.write({
                    'dmag_segment_id': partner.dmag_suggested_segment_id.id,
                    'dmag_stage_g': partner.dmag_stage_g or partner.dmag_suggested_segment_id.stage_g,
                    'dmag_segment_override': False,
                    'dmag_segment_reason': False,
                })
