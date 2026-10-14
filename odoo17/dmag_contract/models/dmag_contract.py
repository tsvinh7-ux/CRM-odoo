from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round

PAID_STATES = ('paid', 'in_payment', 'reversed')


class DmagContract(models.Model):
    _name = 'dmag.contract'
    _description = 'Hợp đồng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_sign desc, id desc'

    name = fields.Char('Số hợp đồng', required=True, copy=False, readonly=True, default=lambda self: _('Mới'))
    title = fields.Char('Tên hợp đồng', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Phòng khám', required=True, tracking=True, index=True,
                                 domain=[('is_company', '=', True)])
    lead_id = fields.Many2one('crm.lead', string='Cơ hội', index=True, tracking=True)
    sale_order_id = fields.Many2one('sale.order', string='Đơn bán', required=True, index=True, tracking=True,
                                    domain="[('partner_id', 'child_of', partner_id)]")
    prescription_id = fields.Many2one(related='sale_order_id.dmag_prescription_id', string='Đơn kê')
    user_id = fields.Many2one('res.users', string='Người phụ trách', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='sale_order_id.currency_id')
    date_sign = fields.Date('Ngày ký', tracking=True)
    date_start = fields.Date('Ngày hiệu lực', tracking=True)
    date_end = fields.Date('Ngày hết hạn', tracking=True)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('signed', 'Đã ký'),
        ('done', 'Hoàn tất'),
        ('cancel', 'Huỷ'),
    ], string='Trạng thái', default='draft', required=True, tracking=True)
    schedule_pattern = fields.Char('Tỷ lệ các đợt (%)', default='40,40,20',
                                   help='Ví dụ 40,40,20 hoặc 50,50. Tổng phải bằng 100.')
    schedule_interval_days = fields.Integer('Khoảng cách giữa các đợt (ngày)', default=30)
    schedule_ids = fields.One2many('dmag.contract.schedule', 'contract_id', string='Lịch thu', copy=False)
    invoice_ids = fields.Many2many('account.move', compute='_compute_amounts', string='Hoá đơn')
    amount_total = fields.Monetary('Giá trị hợp đồng', related='sale_order_id.amount_total')
    amount_invoiced = fields.Monetary('Đã xuất hoá đơn', compute='_compute_amounts')
    amount_paid = fields.Monetary('Đã thu', compute='_compute_amounts')
    amount_due = fields.Monetary('Còn phải thu', compute='_compute_amounts')
    amount_overdue = fields.Monetary('Quá hạn', compute='_compute_amounts')
    paid_percent = fields.Float('% đã thu', compute='_compute_amounts')
    signed_document = fields.Binary('Bản hợp đồng đã ký', attachment=True)
    signed_document_name = fields.Char()
    terms = fields.Html('Điều khoản chính')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Mới')) == _('Mới'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dmag.contract') or _('Mới')
        return super().create(vals_list)

    @api.depends('schedule_ids.invoice_id.amount_residual', 'schedule_ids.invoice_id.state', 'sale_order_id.amount_total')
    def _compute_amounts(self):
        today = fields.Date.today()
        for contract in self:
            invoices = contract.schedule_ids.invoice_id.filtered(lambda inv: inv.state == 'posted')
            contract.invoice_ids = contract.schedule_ids.invoice_id
            contract.amount_invoiced = sum(invoices.mapped('amount_total'))
            contract.amount_paid = sum(inv.amount_total - inv.amount_residual for inv in invoices)
            contract.amount_due = contract.amount_total - contract.amount_paid
            contract.amount_overdue = sum(inv.amount_residual for inv in invoices
                                          if inv.invoice_date_due and inv.invoice_date_due < today)
            contract.paid_percent = 100.0 * contract.amount_paid / contract.amount_total if contract.amount_total else 0.0

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        if self.sale_order_id:
            self.partner_id = self.sale_order_id.partner_id.commercial_partner_id
            self.lead_id = self.sale_order_id.opportunity_id
            self.title = self.title or self.sale_order_id.dmag_prescription_id.name or self.sale_order_id.name

    def _parse_pattern(self):
        self.ensure_one()
        try:
            parts = [float(p) for p in (self.schedule_pattern or '').replace(';', ',').split(',') if p.strip()]
        except ValueError as exc:
            raise ValidationError(_('Tỷ lệ các đợt phải là số, ví dụ 40,40,20.')) from exc
        if not parts or float_compare(sum(parts), 100.0, precision_digits=2):
            raise ValidationError(_('Tổng tỷ lệ các đợt phải bằng 100%% (đang là %s%%).', sum(parts)))
        return parts

    def action_generate_schedule(self):
        for contract in self:
            if contract.schedule_ids.filtered('invoice_id'):
                raise UserError(_('Đã có đợt xuất hoá đơn, không thể sinh lại lịch thu.'))
            start = contract.date_start or contract.date_sign or fields.Date.today()
            parts = contract._parse_pattern()
            contract.schedule_ids = [fields.Command.clear()] + [fields.Command.create({
                'sequence': index,
                'name': _('Đợt %s', index),
                'percent': percent,
                'due_date': start + timedelta(days=contract.schedule_interval_days * (index - 1)),
            }) for index, percent in enumerate(parts, start=1)]

    def action_sign(self):
        for contract in self:
            if not contract.schedule_ids:
                contract.action_generate_schedule()
            order = contract.sale_order_id
            if order.state in ('draft', 'sent'):
                order.action_confirm()
            contract.write({'state': 'signed', 'date_sign': contract.date_sign or fields.Date.today(),
                            'date_start': contract.date_start or contract.date_sign or fields.Date.today()})
            if contract.lead_id and contract.lead_id.active and not contract.lead_id.stage_id.is_won:
                contract.message_post(body=_('Hợp đồng đã ký. Hãy chuyển cơ hội %s sang "Thắng" khi nhận cọc.',
                                             contract.lead_id.display_name))

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_out_invoice_type')
        action['domain'] = [('id', 'in', self.schedule_ids.invoice_id.ids)]
        action['context'] = {'default_move_type': 'out_invoice', 'create': False}
        return action

    @api.model
    def _cron_payment_reminders(self):
        """Nhắc người phụ trách: đợt sắp đến hạn chưa xuất hoá đơn, và hoá đơn đợt đã quá hạn."""
        today = fields.Date.today()
        lines = self.env['dmag.contract.schedule'].search([('contract_id.state', '=', 'signed')])
        for line in lines:
            contract = line.contract_id
            user = contract.user_id or self.env.user
            if not line.invoice_id and line.due_date and line.due_date <= today + timedelta(days=3) and not line.reminded:
                contract.activity_schedule('mail.mail_activity_data_todo', date_deadline=line.due_date, user_id=user.id,
                                           summary=_('Xuất hoá đơn %(line)s – %(contract)s', line=line.name, contract=contract.name))
                line.reminded = True
            elif line.state == 'overdue' and not line.overdue_reminded:
                contract.activity_schedule('mail.mail_activity_data_call', date_deadline=today, user_id=user.id,
                                           summary=_('Thu nợ %(line)s quá hạn – %(contract)s', line=line.name, contract=contract.name))
                line.overdue_reminded = True


class DmagContractSchedule(models.Model):
    _name = 'dmag.contract.schedule'
    _description = 'Đợt thu theo hợp đồng'
    _order = 'contract_id, sequence, id'

    contract_id = fields.Many2one('dmag.contract', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=1)
    name = fields.Char('Đợt', required=True)
    percent = fields.Float('Tỷ lệ (%)', required=True)
    currency_id = fields.Many2one(related='contract_id.currency_id')
    amount = fields.Monetary('Số tiền', compute='_compute_amount')
    due_date = fields.Date('Hạn thu')
    invoice_id = fields.Many2one('account.move', string='Hoá đơn', readonly=True, copy=False)
    payment_state = fields.Selection(related='invoice_id.payment_state', string='Thanh toán')
    amount_residual = fields.Monetary(related='invoice_id.amount_residual', string='Còn nợ')
    state = fields.Selection([
        ('to_invoice', 'Chưa xuất HĐ'),
        ('invoiced', 'Đã xuất HĐ'),
        ('paid', 'Đã thu'),
        ('overdue', 'Quá hạn'),
    ], compute='_compute_state', string='Trạng thái')
    reminded = fields.Boolean(copy=False)
    overdue_reminded = fields.Boolean(copy=False)

    @api.depends('percent', 'contract_id.amount_total')
    def _compute_amount(self):
        for line in self:
            line.amount = line.contract_id.amount_total * line.percent / 100.0

    @api.depends('invoice_id.payment_state', 'invoice_id.state', 'invoice_id.invoice_date_due')
    def _compute_state(self):
        today = fields.Date.today()
        for line in self:
            invoice = line.invoice_id
            if not invoice or invoice.state == 'cancel':
                line.state = 'to_invoice'
            elif invoice.payment_state in PAID_STATES:
                line.state = 'paid'
            elif invoice.state == 'posted' and invoice.invoice_date_due and invoice.invoice_date_due < today:
                line.state = 'overdue'
            else:
                line.state = 'invoiced'

    def action_create_invoice(self):
        """Hoá đơn đợt = các dòng đơn bán × tỷ lệ đợt (giữ nguyên sản phẩm để tính hoa hồng, thuế, doanh thu)."""
        for line in self:
            contract = line.contract_id
            if contract.state != 'signed':
                raise UserError(_('Chỉ xuất hoá đơn cho hợp đồng đã ký.'))
            if line.invoice_id and line.invoice_id.state != 'cancel':
                raise UserError(_('%s đã có hoá đơn.', line.name))
            order = contract.sale_order_id
            is_last = line == contract.schedule_ids.sorted('sequence')[-1:]
            invoice_vals = order._prepare_invoice()
            invoice_vals['invoice_date_due'] = line.due_date
            invoice_vals['ref'] = f'{contract.name} – {line.name}'
            line_vals = []
            for sale_line in order.order_line.filtered(lambda l: not l.display_type and not l.is_downpayment):
                precision = sale_line.product_uom.rounding or 0.01
                if is_last:
                    quantity = sale_line.product_uom_qty - sale_line.qty_invoiced
                else:
                    quantity = float_round(sale_line.product_uom_qty * line.percent / 100.0, precision_rounding=precision)
                if quantity <= 0:
                    continue
                line_vals.append(fields.Command.create(sale_line._prepare_invoice_line(quantity=quantity)))
            if not line_vals:
                raise UserError(_('Không còn gì để xuất hoá đơn cho %s.', line.name))
            invoice_vals['invoice_line_ids'] = line_vals
            invoice = self.env['account.move'].sudo().with_company(order.company_id).create(invoice_vals)
            line.invoice_id = invoice
            contract.message_post(body=_('Đã tạo hoá đơn %(inv)s cho %(line)s.', inv=invoice.display_name, line=line.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self[:1].invoice_id.id,
            'view_mode': 'form',
        }


class DmagContractDemo(models.AbstractModel):
    _name = 'dmag.contract.demo'
    _description = 'Tiện ích dữ liệu minh hoạ hợp đồng'

    @api.model
    def _run(self, order_ids):
        """Tạo hợp đồng 40/40/20 cho đơn, ký, xuất và thu đợt 1 (dùng cho demo)."""
        for order in self.env['sale.order'].browse(order_ids):
            contract = self.env['dmag.contract'].browse(order.action_dmag_create_contract()['res_id'])
            contract.action_sign()
            first = contract.schedule_ids.sorted('sequence')[:1]
            first.action_create_invoice()
            first.invoice_id.action_post()
            self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=first.invoice_id.ids).create({})._create_payments()
