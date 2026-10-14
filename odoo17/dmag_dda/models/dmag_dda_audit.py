import math

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

PASS_TOTAL = 75.0
DSO_TOTAL = 85.0

# Màu 4 lớp Radar theo báo cáo DDA mẫu: Tự chấm (cam), Genba (đỏ), Chuẩn MSO (tím), Chuẩn DSO (xanh).
RADAR_SERIES = [
    ('self', 'Tự chấm', '#f59e0b'),
    ('genba', 'Genba (DMAG chấm)', '#dc2626'),
    ('pass', 'Sàn đạt', '#7c3aed'),
    ('dso', 'Chuẩn DSO', '#2563eb'),
]


class DmagDdaAudit(models.Model):
    _name = 'dmag.dda.audit'
    _description = 'Kiểm toán chẩn đoán DDA'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_onsite desc, id desc'

    name = fields.Char('Mã hồ sơ', required=True, copy=False, readonly=True, default=lambda self: _('Mới'))
    partner_id = fields.Many2one('res.partner', string='Phòng khám', required=True, tracking=True,
                                 domain=[('is_company', '=', True)], index=True)
    lead_id = fields.Many2one('crm.lead', string='Cơ hội', index=True)
    auditor_id = fields.Many2one('res.users', string='Chuyên viên onsite', default=lambda self: self.env.user,
                                 tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Người thẩm định', tracking=True)
    date_onsite = fields.Date('Ngày onsite', tracking=True)
    date_decision = fields.Date('Ngày phán quyết', readonly=True)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('deposit', 'Đã cọc'),
        ('onsite', 'Đang onsite'),
        ('review', 'Chờ thẩm định'),
        ('done', 'Đã phán quyết'),
        ('cancel', 'Huỷ'),
    ], default='draft', required=True, tracking=True)
    is_reaudit = fields.Boolean('Đo lại (DDA lần 2+)')
    line_ids = fields.One2many('dmag.dda.audit.line', 'audit_id', string='Chấm điểm', copy=True,
                               default=lambda self: self._default_line_ids())
    total_self = fields.Float('Tổng tự chấm', compute='_compute_totals', store=True)
    total_genba = fields.Float('Tổng Genba', compute='_compute_totals', store=True, tracking=True)
    perception_gap = fields.Float('Lệch nhận thức', compute='_compute_totals', store=True)
    t1_redflag = fields.Boolean('Cờ đỏ điểm liệt', compute='_compute_totals', store=True)
    segment_id = fields.Many2one('dmag.segment', string='Phân khúc theo DDA', compute='_compute_totals', store=True)
    stage_g = fields.Selection(related='segment_id.stage_g', string='Chặng')
    flow = fields.Integer('Luồng', compute='_compute_totals', store=True)
    pass_ok = fields.Boolean('Đạt sàn 75', compute='_compute_totals', store=True)
    dso_ok = fields.Boolean('Đạt chuẩn DSO 85', compute='_compute_totals', store=True)
    conclusion = fields.Html('Kết luận hội đồng')
    radar_svg = fields.Html('Radar', compute='_compute_radar_svg', sanitize=False)
    prescription_ids = fields.One2many('dmag.prescription', 'audit_id', string='Đơn kê')
    prescription_count = fields.Integer(compute='_compute_prescription_count')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model
    def _default_line_ids(self):
        return [fields.Command.create({'pillar_id': pillar.id}) for pillar in self.env['dmag.pillar'].search([])]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Mới')) == _('Mới'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dmag.dda.audit') or _('Mới')
        return super().create(vals_list)

    @api.depends('line_ids.self_score', 'line_ids.genba_score', 'line_ids.pillar_id')
    def _compute_totals(self):
        Segment = self.env['dmag.segment']
        for audit in self:
            audit.total_self = sum(audit.line_ids.mapped('self_score'))
            audit.total_genba = sum(audit.line_ids.mapped('genba_score'))
            audit.perception_gap = audit.total_self - audit.total_genba
            audit.t1_redflag = any(
                line.pillar_id.is_knockout and line.genba_score < line.pillar_id.pass_score for line in audit.line_ids)
            segment = Segment._find_by_score(audit.total_genba)
            audit.segment_id = segment
            audit.flow = 1 if audit.t1_redflag else segment.flow
            audit.pass_ok = audit.total_genba >= PASS_TOTAL
            audit.dso_ok = audit.total_genba >= DSO_TOTAL

    def _compute_prescription_count(self):
        for audit in self:
            audit.prescription_count = len(audit.prescription_ids)

    # ------------------------------------------------------------------
    # Radar
    # ------------------------------------------------------------------
    def _radar_values(self):
        self.ensure_one()
        lines = self.line_ids.sorted(lambda line: (line.pillar_id.sequence, line.pillar_id.id))
        return {
            'labels': lines.mapped('pillar_id.code'),
            'self': lines.mapped('self_score'),
            'genba': lines.mapped('genba_score'),
            'pass': lines.mapped('pillar_id.pass_score'),
            'dso': lines.mapped('pillar_id.dso_score'),
        }

    @api.depends('line_ids.self_score', 'line_ids.genba_score')
    def _compute_radar_svg(self):
        for audit in self:
            audit.radar_svg = audit._render_radar_svg()

    def _render_radar_svg(self, size=380):
        self.ensure_one()
        data = self._radar_values()
        count = len(data['labels'])
        if count < 3:
            return Markup('<p class="text-muted">Cần ít nhất 3 trụ cột để vẽ Radar.</p>')
        center, radius = size / 2, size / 2 - 50

        def point(index, value):
            angle = -math.pi / 2 + 2 * math.pi * index / count
            dist = radius * max(0.0, min(value, 10.0)) / 10.0
            return center + dist * math.cos(angle), center + dist * math.sin(angle)

        def polygon(values):
            return ' '.join('%.1f,%.1f' % point(i, v) for i, v in enumerate(values))

        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size + 50}" '
                 f'width="{size}" height="{size + 50}" style="max-width:100%;font-family:sans-serif">']
        for level in (2, 4, 6, 8, 10):
            parts.append(f'<polygon points="{polygon([level] * count)}" fill="none" stroke="#d1d5db" stroke-width="1"/>')
        for i, label in enumerate(data['labels']):
            x, y = point(i, 10)
            lx, ly = point(i, 11.6)
            parts.append(f'<line x1="{center}" y1="{center}" x2="{x:.1f}" y2="{y:.1f}" stroke="#e5e7eb"/>')
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="12" text-anchor="middle" '
                         f'dominant-baseline="middle" fill="#374151">{escape(label)}</text>')
        for key, _label, color in reversed(RADAR_SERIES):
            dash = ' stroke-dasharray="4 3"' if key in ('pass', 'dso') else ''
            fill_opacity = '0.18' if key in ('self', 'genba') else '0'
            parts.append(f'<polygon points="{polygon(data[key])}" fill="{color}" fill-opacity="{fill_opacity}" '
                         f'stroke="{color}" stroke-width="2"{dash}/>')
        for i, (_key, label, color) in enumerate(RADAR_SERIES):
            x = 20 + (i % 2) * (size / 2)
            legend_y = size + 10 + (i // 2) * 20
            parts.append(f'<rect x="{x:.0f}" y="{legend_y - 9}" width="10" height="10" fill="{color}"/>'
                         f'<text x="{x + 14:.0f}" y="{legend_y}" font-size="11" fill="#374151">{escape(label)}</text>')
        parts.append('</svg>')
        return Markup(''.join(parts))

    # ------------------------------------------------------------------
    # Quy trình
    # ------------------------------------------------------------------
    def action_mark_deposit(self):
        self.write({'state': 'deposit'})

    def action_start_onsite(self):
        for audit in self:
            audit.write({'state': 'onsite', 'date_onsite': audit.date_onsite or fields.Date.today()})

    def action_submit_review(self):
        for audit in self:
            missing = audit.line_ids.filtered(lambda line: not line.scored)
            if missing:
                raise UserError(_('Chưa chấm đủ 10 trụ cột: %s', ', '.join(missing.mapped('pillar_id.code'))))
        self.write({'state': 'review'})

    def action_approve(self):
        """Hội đồng thẩm định phán quyết: cập nhật hồ sơ phòng khám và cơ hội."""
        for audit in self:
            if audit.state != 'review':
                raise UserError(_('Chỉ phán quyết hồ sơ đang ở trạng thái "Chờ thẩm định".'))
            audit.write({'state': 'done', 'date_decision': fields.Date.today(),
                         'reviewer_id': audit.reviewer_id.id or self.env.user.id})
            audit._apply_to_partner()
            audit.message_post(body=_('Phán quyết DDA: %(score)s/100 → %(segment)s, luồng %(flow)s%(flag)s.',
                                      score=audit.total_genba, segment=audit.segment_id.display_name or '—',
                                      flow=audit.flow, flag=_(' · CỜ ĐỎ T1') if audit.t1_redflag else ''))

    def _apply_to_partner(self):
        self.ensure_one()
        clinic = self.partner_id.commercial_partner_id
        vals = {
            'dmag_dda_score': self.total_genba,
            'dmag_dda_date': self.date_decision,
            'dmag_t1_redflag': self.t1_redflag,
        }
        if not clinic.dmag_segment_override and self.segment_id:
            vals['dmag_segment_id'] = self.segment_id.id
            vals['dmag_stage_g'] = self.segment_id.stage_g
        if clinic.dmag_lifecycle in (False, 'follower', 'mql', 'sql'):
            vals['dmag_lifecycle'] = 'diagnosed'
        clinic.write(vals)

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_create_prescription(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError(_('Chỉ kê đơn sau khi hội đồng đã phán quyết DDA.'))
        prescription = self.env['dmag.prescription'].create({
            'audit_id': self.id,
            'partner_id': self.partner_id.commercial_partner_id.id,
            'lead_id': self.lead_id.id,
        })
        prescription.action_generate_lines()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dmag.prescription',
            'res_id': prescription.id,
            'view_mode': 'form',
        }

    def action_view_prescriptions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_dda.action_dmag_prescription')
        action['domain'] = [('audit_id', '=', self.id)]
        return action

    def action_print_radar(self):
        return self.env.ref('dmag_dda.action_report_dmag_dda_audit').report_action(self)

    @api.model
    def _dmag_demo_fill(self, audit_ids, self_scores, genba_scores):
        for audit in self.browse(audit_ids):
            lines = audit.line_ids.sorted(lambda line: (line.pillar_id.sequence, line.pillar_id.id))
            for line, self_score, genba_score in zip(lines, self_scores, genba_scores):
                line.write({'self_score': self_score, 'genba_score': genba_score, 'scored': True})


class DmagDdaAuditLine(models.Model):
    _name = 'dmag.dda.audit.line'
    _description = 'Điểm DDA theo trụ cột'
    _order = 'sequence, id'

    audit_id = fields.Many2one('dmag.dda.audit', required=True, ondelete='cascade', index=True)
    pillar_id = fields.Many2one('dmag.pillar', string='Trụ cột', required=True)
    sequence = fields.Integer(related='pillar_id.sequence', store=True)
    pass_score = fields.Float(related='pillar_id.pass_score', string='Sàn')
    is_knockout = fields.Boolean(related='pillar_id.is_knockout')
    self_score = fields.Float('Tự chấm', default=0.0)
    genba_score = fields.Float('Genba', default=0.0)
    scored = fields.Boolean('Đã chấm', help='Đánh dấu khi chuyên viên đã chấm trụ cột này (kể cả điểm 0).')
    gap = fields.Float('Khoảng thiếu', compute='_compute_gap', store=True)
    result = fields.Selection([
        ('pass', 'Đạt'),
        ('fail', 'Chưa đạt'),
        ('redflag', 'Cờ đỏ'),
    ], compute='_compute_gap', store=True, string='Kết quả')
    finding = fields.Text('Hiện trạng / chứng cứ')
    legal_basis = fields.Char('Căn cứ pháp lý')
    remedy90 = fields.Text('Hướng khắc phục 90 ngày')

    _sql_constraints = [
        ('score_range', 'CHECK(self_score >= 0 AND self_score <= 10 AND genba_score >= 0 AND genba_score <= 10)',
        'Điểm mỗi trụ cột nằm trong khoảng 0–10.'),
    ]

    @api.depends('genba_score', 'pillar_id.pass_score', 'pillar_id.is_knockout')
    def _compute_gap(self):
        for line in self:
            line.gap = max(0.0, line.pillar_id.pass_score - line.genba_score)
            if line.gap <= 0:
                line.result = 'pass'
            elif line.pillar_id.is_knockout:
                line.result = 'redflag'
            else:
                line.result = 'fail'

    @api.onchange('genba_score', 'self_score')
    def _onchange_mark_scored(self):
        for line in self:
            line.scored = True
