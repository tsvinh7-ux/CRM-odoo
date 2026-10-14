from collections import defaultdict

from odoo import _, api, fields, models

from .product_template import COMMISSION_GROUP_SELECTION

ROLE_SELECTION = [
    ('closer', 'Người chốt'),
    ('lead', 'Người tạo/chăm lead'),
    ('owner', 'Account Owner'),
]


class DmagCommissionLine(models.Model):
    """Một dòng hoa hồng phát sinh khi một khoản thu được đối soát vào hoá đơn."""
    _name = 'dmag.commission.line'
    _description = 'Dòng hoa hồng (theo thực thu)'
    _order = 'date desc, id desc'

    user_id = fields.Many2one('res.users', string='Người hưởng', required=True, index=True)
    role = fields.Selection(ROLE_SELECTION, string='Vai trò', required=True)
    share = fields.Float('Tỷ lệ chia (%)')
    date = fields.Date('Ngày thu', required=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Khách hàng', index=True)
    invoice_id = fields.Many2one('account.move', string='Hoá đơn', index=True)
    sale_order_id = fields.Many2one('sale.order', string='Đơn bán')
    product_id = fields.Many2one('product.product', string='Sản phẩm')
    commission_group = fields.Selection(COMMISSION_GROUP_SELECTION, string='Nhóm')
    partial_id = fields.Many2one('account.partial.reconcile', string='Đối soát', ondelete='set null', index=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    base_amount = fields.Monetary('Thực thu chưa VAT', help='Phần doanh thu chưa VAT tương ứng với số tiền đã thu.')
    rate = fields.Float('Tỷ lệ (%)')
    amount = fields.Monetary('Hoa hồng')
    is_clawback = fields.Boolean('Trừ lại', help='Dòng âm khi đối soát bị huỷ hoặc hoàn tiền.')
    origin_line_id = fields.Many2one('dmag.commission.line', string='Dòng gốc')
    statement_id = fields.Many2one('dmag.commission.statement', string='Bảng kê', index=True, ondelete='set null')
    statement_state = fields.Selection(related='statement_id.state', string='Trạng thái bảng kê')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    # ------------------------------------------------------------------
    # Sinh dòng hoa hồng từ đối soát
    # ------------------------------------------------------------------
    @api.model
    def _beneficiaries(self, invoice, order):
        """Trả về {user: [(role, share%)]} theo quy tắc chia của công ty.

        Vai trò thiếu người thì phần đó dồn cho người chốt; một người giữ nhiều vai thì cộng dồn.
        """
        company = invoice.company_id
        closer = order.user_id or invoice.invoice_user_id
        lead_owner = order.opportunity_id.dmag_lead_owner_id if order else self.env['res.users']
        account_owner = invoice.commercial_partner_id.dmag_account_owner_id
        result = defaultdict(list)
        if not closer:
            return result
        for role, user, share in (
            ('closer', closer, company.dmag_split_closer),
            ('lead', lead_owner, company.dmag_split_lead),
            ('owner', account_owner, company.dmag_split_owner),
        ):
            result[user or closer].append((role if user else 'closer', share))
        return result

    @api.model
    def _create_from_partials(self, partials):
        vals_list = []
        for partial in partials:
            vals_list += self._vals_from_partial(partial)
        return self.create(vals_list) if vals_list else self.browse()

    @api.model
    def _vals_from_partial(self, partial):
        sides = ((partial.debit_move_id, partial.credit_move_id), (partial.credit_move_id, partial.debit_move_id))
        for invoice_aml, counter_aml in sides:
            invoice = invoice_aml.move_id
            counter = counter_aml.move_id
            if invoice.move_type in ('out_invoice', 'out_refund') and not counter.is_sale_document(include_receipts=True):
                break
        else:
            return []
        if not invoice.amount_total_signed:
            return []
        sign = -1 if invoice.move_type == 'out_refund' else 1
        ratio = partial.amount / abs(invoice.amount_total_signed)
        day = max(partial.debit_move_id.date, partial.credit_move_id.date)
        Assignment = self.env['dmag.commission.assignment']
        vals_list = []
        for line in invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product' and l.product_id):
            base = sign * abs(line.balance) * ratio
            group = line.product_id.product_tmpl_id.dmag_commission_group or 'other'
            order = line.sale_line_ids.order_id[:1]
            for user, roles in self._beneficiaries(invoice, order).items():
                assignment = Assignment._get_for(user, day)
                if not assignment:
                    continue
                rate = assignment._rate_for(group)
                if not rate:
                    continue
                for role, share in roles:
                    vals_list.append({
                        'user_id': user.id,
                        'role': role,
                        'share': share,
                        'date': day,
                        'partner_id': invoice.commercial_partner_id.id,
                        'invoice_id': invoice.id,
                        'sale_order_id': order.id,
                        'product_id': line.product_id.id,
                        'commission_group': group,
                        'partial_id': partial.id,
                        'currency_id': invoice.company_id.currency_id.id,
                        'base_amount': base,
                        'rate': rate,
                        'amount': base * share / 100.0 * rate / 100.0,
                        'company_id': invoice.company_id.id,
                    })
        return vals_list

    def _create_clawbacks(self):
        """Đối soát bị huỷ: sinh dòng âm vào kỳ hiện tại, không sửa bảng kê đã duyệt."""
        today = fields.Date.today()
        to_reverse = self.filtered(lambda l: not l.is_clawback)
        return self.create([{
            'user_id': line.user_id.id,
            'role': line.role,
            'share': line.share,
            'date': today,
            'partner_id': line.partner_id.id,
            'invoice_id': line.invoice_id.id,
            'sale_order_id': line.sale_order_id.id,
            'product_id': line.product_id.id,
            'commission_group': line.commission_group,
            'currency_id': line.currency_id.id,
            'base_amount': -line.base_amount,
            'rate': line.rate,
            'amount': -line.amount,
            'is_clawback': True,
            'origin_line_id': line.id,
            'company_id': line.company_id.id,
        } for line in to_reverse]) if to_reverse else self.browse()

    @api.depends('user_id', 'invoice_id', 'role')
    def _compute_display_name(self):
        labels = dict(ROLE_SELECTION)
        for line in self:
            line.display_name = _('%(user)s · %(role)s · %(inv)s', user=line.user_id.name or '',
                                  role=labels.get(line.role, ''), inv=line.invoice_id.name or '')
