from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dmag_crm.models.dmag_segment import TIER_ORDER, TIER_SELECTION

# Ngưỡng khoảng thiếu (điểm/10) → hình thức gợi ý. Bản nháp, chờ DMAG chốt.
GAP_RULES = [
    (1.0, 'self'),
    (3.0, 'guided'),
    (5.0, 'one_on_one'),
]
FOUNDATION_PILLARS = ('T2', 'T3')


def suggest_tier(gap, pillar, segment):
    """Gợi ý hình thức triển khai cho một trụ cột chưa đạt.

    - Trụ cột điểm liệt (T1) chưa đạt: thực địa.
    - Còn lại theo khoảng thiếu: ≤1 tự học, ≤3 có hướng dẫn, ≤5 kèm 1:1, >5 thực địa.
    - Kẹp theo hình thức phân khúc được phép bán (vd. PK1 không có 1:1 / thực địa).
    """
    if gap <= 0:
        return False
    if pillar.is_knockout:
        tier = 'field'
    else:
        tier = next((code for limit, code in GAP_RULES if gap <= limit), 'field')
    allowed = segment._allowed_tiers() if segment else TIER_ORDER
    if not allowed:
        return tier
    candidates = [code for code in allowed if TIER_ORDER.index(code) <= TIER_ORDER.index(tier)]
    return candidates[-1] if candidates else allowed[0]


def priority_key(pillar, gap):
    """T1 trước, sau đó nền móng T2–T3, còn lại theo khoảng thiếu lớn trước."""
    if pillar.is_knockout:
        rank = 0
    elif pillar.code in FOUNDATION_PILLARS:
        rank = 1
    else:
        rank = 2
    return (rank, -gap, pillar.sequence)


class DmagPrescription(models.Model):
    _name = 'dmag.prescription'
    _description = 'Đơn kê lộ trình'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Mã đơn kê', required=True, copy=False, readonly=True, default=lambda self: _('Mới'))
    audit_id = fields.Many2one('dmag.dda.audit', string='Hồ sơ DDA', index=True)
    partner_id = fields.Many2one('res.partner', string='Phòng khám', required=True, tracking=True,
                                 domain=[('is_company', '=', True)], index=True)
    lead_id = fields.Many2one('crm.lead', string='Cơ hội', index=True, tracking=True)
    segment_id = fields.Many2one('dmag.segment', string='Phân khúc', compute='_compute_segment', store=True,
                                 readonly=False)
    t1_redflag = fields.Boolean(related='partner_id.dmag_t1_redflag', string='Cờ đỏ T1')
    user_id = fields.Many2one('res.users', string='Chuyên viên kê đơn', default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('confirmed', 'Đã duyệt'),
        ('quoted', 'Đã báo giá'),
        ('cancel', 'Huỷ'),
    ], default='draft', required=True, tracking=True)
    line_ids = fields.One2many('dmag.prescription.line', 'prescription_id', string='Module', copy=True)
    allow_out_of_segment = fields.Boolean('Cho phép ngoài phân khúc',
                                          help='Quản lý bật khi cần kê hình thức không thuộc phân khúc.')
    sale_order_id = fields.Many2one('sale.order', string='Báo giá', readonly=True, copy=False)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    amount_total = fields.Monetary('Tổng giá trị', compute='_compute_amount_total')
    uses_field_tier = fields.Boolean('Có triển khai thực địa', compute='_compute_amount_total')
    note = fields.Html('Ghi chú tư vấn')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Mới')) == _('Mới'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dmag.prescription') or _('Mới')
        return super().create(vals_list)

    @api.depends('partner_id', 'audit_id.segment_id')
    def _compute_segment(self):
        for prescription in self:
            prescription.segment_id = (prescription.partner_id.commercial_partner_id.dmag_segment_id
                                       or prescription.audit_id.segment_id)

    @api.depends('line_ids.price_unit', 'line_ids.tier')
    def _compute_amount_total(self):
        for prescription in self:
            prescription.amount_total = sum(prescription.line_ids.mapped('price_unit'))
            prescription.uses_field_tier = any(line.tier == 'field' for line in prescription.line_ids)

    def action_generate_lines(self):
        """Sinh dòng đơn kê từ Radar: mỗi trụ cột chưa đạt → 1 module, hình thức theo quy tắc."""
        Product = self.env['product.product']
        for prescription in self:
            if not prescription.audit_id:
                raise UserError(_('Đơn kê cần gắn với một hồ sơ DDA đã phán quyết.'))
            failing = prescription.audit_id.line_ids.filtered(lambda line: line.gap > 0)
            ordered = failing.sorted(lambda line: priority_key(line.pillar_id, line.gap))
            commands = [fields.Command.clear()]
            for index, line in enumerate(ordered, start=1):
                tier = suggest_tier(line.gap, line.pillar_id, prescription.segment_id)
                product = Product._dmag_find_module(line.pillar_id, tier)
                commands.append(fields.Command.create({
                    'sequence': index,
                    'pillar_id': line.pillar_id.id,
                    'gap': line.gap,
                    'suggested_tier': tier,
                    'tier': tier,
                    'product_id': product.id,
                    'price_unit': product.lst_price if product else 0.0,
                    'remedy90': line.remedy90,
                }))
            prescription.line_ids = commands

    def _check_rules(self):
        for prescription in self:
            if not prescription.line_ids:
                raise UserError(_('Đơn kê chưa có module nào.'))
            missing = prescription.line_ids.filtered(lambda line: not line.product_id)
            if missing:
                raise UserError(_('Chưa có sản phẩm trong danh mục cho: %s. Chọn sản phẩm hoặc bổ sung danh mục module.',
                                  ', '.join(missing.mapped('pillar_id.code'))))
            if prescription.t1_redflag:
                others = prescription.line_ids.filtered(lambda line: not line.pillar_id.is_knockout)
                if others:
                    raise UserError(_('Phòng khám đang có cờ đỏ T1: chỉ được kê module khắc phục T1 trước. '
                                      'Hãy bỏ các dòng: %s', ', '.join(others.mapped('pillar_id.code'))))
            if prescription.segment_id and not prescription.allow_out_of_segment:
                allowed = prescription.segment_id._allowed_tiers()
                wrong = prescription.line_ids.filtered(lambda line: line.tier not in allowed)
                if wrong:
                    labels = dict(TIER_SELECTION)
                    raise UserError(_('Phân khúc %(segment)s không bán hình thức: %(tiers)s.',
                                      segment=prescription.segment_id.display_name,
                                      tiers=', '.join(sorted({labels[t] for t in wrong.mapped('tier')}))))

    def action_confirm(self):
        self._check_rules()
        self.write({'state': 'confirmed'})

    def action_create_quotation(self):
        self.ensure_one()
        self._check_rules()
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.commercial_partner_id.id,
            'opportunity_id': self.lead_id.id,
            'dmag_prescription_id': self.id,
            'user_id': (self.lead_id.user_id or self.env.user).id,
            'team_id': self.lead_id.team_id.id or False,
            'order_line': [fields.Command.create({
                'product_id': line.product_id.id,
                'product_uom_qty': 1,
                'price_unit': line.price_unit,
                'name': line._sale_line_description(),
            }) for line in self.line_ids.sorted('sequence')],
        })
        self.write({'state': 'quoted', 'sale_order_id': order.id})
        if self.lead_id and self.uses_field_tier:
            self.lead_id.dmag_uses_capacity = True
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
        }

    def action_create_opportunity(self):
        """Tạo cơ hội ở pipeline P2 cho đơn kê chưa gắn cơ hội."""
        team = self.env.ref('dmag_crm.team_prescription')
        for prescription in self.filtered(lambda p: not p.lead_id):
            prescription.lead_id = self.env['crm.lead'].create({
                'name': _('%s – Lộ trình module', prescription.partner_id.name),
                'type': 'opportunity',
                'partner_id': prescription.partner_id.id,
                'team_id': team.id,
                'user_id': prescription.user_id.id,
                'expected_revenue': prescription.amount_total,
            })

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})


class DmagPrescriptionLine(models.Model):
    _name = 'dmag.prescription.line'
    _description = 'Dòng đơn kê lộ trình'
    _order = 'sequence, id'

    prescription_id = fields.Many2one('dmag.prescription', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    pillar_id = fields.Many2one('dmag.pillar', string='Trụ cột', required=True)
    gap = fields.Float('Khoảng thiếu')
    suggested_tier = fields.Selection(TIER_SELECTION, string='Hình thức gợi ý', readonly=True)
    tier = fields.Selection(TIER_SELECTION, string='Hình thức', required=True)
    is_override = fields.Boolean('Đã sửa gợi ý', compute='_compute_is_override', store=True)
    product_id = fields.Many2one('product.product', string='Module',
                                 domain="[('product_tmpl_id.dmag_is_module', '=', True)]")
    price_unit = fields.Float('Giá')
    remedy90 = fields.Text('Mục tiêu 90 ngày')

    @api.depends('tier', 'suggested_tier')
    def _compute_is_override(self):
        for line in self:
            line.is_override = bool(line.suggested_tier) and line.tier != line.suggested_tier

    @api.onchange('tier', 'pillar_id')
    def _onchange_tier(self):
        for line in self:
            if line.pillar_id and line.tier:
                product = self.env['product.product']._dmag_find_module(line.pillar_id, line.tier)
                line.product_id = product
                line.price_unit = product.lst_price if product else 0.0

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.price_unit = line.product_id.lst_price

    def _sale_line_description(self):
        self.ensure_one()
        tier_label = dict(TIER_SELECTION).get(self.tier, '')
        description = f'{self.product_id.display_name} — {tier_label} ({self.pillar_id.code})'
        if self.remedy90:
            description += f'\nMục tiêu 90 ngày: {self.remedy90}'
        return description
