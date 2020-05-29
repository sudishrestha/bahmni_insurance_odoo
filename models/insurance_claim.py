from odoo import models, fields, api
import logging
import json
from odoo.exceptions import UserError

import odoo.addons.decimal_precision as dp
from xmlrpclib import DateTime
from difflib import _calculate_ratio

_logger = logging.getLogger(__name__)

class claims(models.Model):
    _name = 'insurance.claim'
    _description = 'Claims'
    _inherit = ['mail.thread']

    @api.depends('insurance_claim_line.price_total')
    def _claimed_amount_all(self):
        """
        Compute the total amounts of the claim
        """
        _logger.info("Inside _amount_all")
        for claim in self:
            claimed_amount_total = 0.0
            
            for line in claim.insurance_claim_line:
                claimed_amount_total += line.price_total
                
            claim.update({
                'claimed_amount_total': claimed_amount_total
            })    
        
    @api.multi
    def action_track_status(self):
        '''
            Track Status of the claims
        '''
        _logger.info("action_track_status")
        claim = self
        
        if claim.state in ('draft', 'rejected', 'confirmed'):
            raise UserError("Claim has not been submitted to be tracked")
        if not claim.claim_code:
            raise UserError("Claim has not been submitted to be tracked")

        #Track Claim
        response = self.env['insurance.connect']._track_claim(claim.claim_code)
        if response:
            self.update_claim_from_claim_response(claim, response)
            
    
    @api.multi
    def print_claim(self):
        '''
            Print Claim
        '''
        _logger.info("print_claim")
        
        raise UserError("Currently this feature is not available")
    
    @api.multi
    def action_adjust_payment(self):
        '''
            Adjust the amount received from the claim
        '''
        _logger.info("Inside action_adjust_payment")
        
        raise UserError("Currently this feature is not available")
    
        
    
    @api.multi
    @api.onchange('sale_orders')
    def onchange_sale_orders_add_claim(self):
        """
        Trigger the change of sale order to add claims for associated sale orders
        """
        _logger.info("onchange_sale_orders_add_claim")

    @api.model
    @api.onchange('partner_id', 'id')
    def _get_insurance_details(self):
        """
            Get insurance details
        """
        _logger.info("_get_insurance_details")
        return 'a'
        # for claim in self:
        #     _logger.info(claim.partner_id.id)
        #     _logger.info(claim.id)
        #     _logger.info("______")
        #     insurance_eligibility = self.env['insurance.eligibility']._get_insurance_details(claim.partner_id)
        #     if insurance_eligibility:
        #         self.insurance_eligibility = insurance_eligibility
        #         _logger.info(self.insurance_eligibility)
                
    def _check_if_eligible(self, claim):
        _logger.info("_check_eligiblity")
        insurance_eligibility = self.env['insurance.eligibility']._get_insurance_details(claim.partner_id)

        if claim.claimed_amount_total > insurance_eligibility['eligibility_balance']:
            _logger.info("Claimed amount greater than amount eligible")
            return False
        else: 
            return True
            
    
    @api.multi
    def _create_claim(self, sale_order):
        '''
            Create/Update claims
        '''
        _logger.info("_create_claim")
        _logger.info(sale_order)
        if sale_order and sale_order.payment_type in ('insurance', 'partial'):
            '''
                Create and save claims
            '''
            if sale_order.nhis_number is None or len(sale_order.nhis_number) == 0:
                raise UserError("Claim can't be created. NHIS number is not present.")
            
            insurance_sale_order_lines = sale_order.order_line.filtered(lambda r: r.payment_type == 'insurance')
            if len(insurance_sale_order_lines) == 0 :
                raise UserError("No Sales order line marked as Insurance Payment type")
            
            visit_uuid = sale_order.external_visit_uuid
            
            if visit_uuid is None:
                raise UserError("Sales order doesn't have visit id to be associated with claim")
            
            claim_in_db = self.env['insurance.claim'].search([('external_visit_uuid', '=', visit_uuid)])
            
            if claim_in_db:
                '''Update existing claim'''
                _logger.info("About to edit claim")
                    
                ''' Update contents of claim only if claim is partial or insurance'''
                    
                ''' Update contents of claim line only if payment type is insurance'''
                ''' Check whether a given product has a line item, if yes add quantity, if no add line item'''
                if claim_in_db.state in ['confirmed','submitted']:
                    raise UserError("Claim in %s state. Claim should be in draft state to be editable. So new items can't be added"%(claim_in_db.state))
                
                if sale_order.id not in claim_in_db.sale_orders.ids:
                    claim_in_db.update({'sale_orders': claim_in_db.sale_orders + sale_order})
            else:
                '''Create new claim'''
                _logger.info("About to Create new claim")
                insurance_sale_order_lines = sale_order.order_line.filtered(lambda r: r.payment_type == 'insurance')
                if len(insurance_sale_order_lines) == 0 :
                    raise UserError("No Sales order line marked as Insurance Payment type")
                    
                claim = {
                    'claim_manager_id' : sale_order.user_id.id,
                    'claimed_date' : sale_order.create_date,
                    'partner_id' : sale_order.partner_id.id,
                    'state' : 'draft',
                    'external_visit_uuid' : sale_order.external_visit_uuid,
                    'partner_uuid' : sale_order.partner_uuid,
                    'currency_id': sale_order.currency_id.id,
                    'sale_orders': sale_order
                }
                
                _logger.info("claim=%s",claim)
                
                claim_in_db = self.env['insurance.claim'].create(claim)
                
                #Exculsively adding sales order
                claim_in_db.update({'sale_orders': claim_in_db.sale_orders + sale_order})
                
                add_visit_specific_product = self.env['insurance.config.settings']._get_claim_code_setup_option()
                _logger.info("add_visit_specific_product=%s", add_visit_specific_product)
                        
                '''
                    Check if adding visit specific product automatically(from config settings), if yes proceed
                '''
                if add_visit_specific_product:
                    self._add_visit_specific_claim_line(claim_in_db, sale_order)
                      
                
            try:
                _logger.info(claim_in_db)   
                
                # Add insurance claim line
                self._create_claim_line(claim_in_db, sale_order)
                    
                insurance_claim_lines = self.env['insurance.claim.line'].search([('claim_id', '=', claim_in_db.id)])
                if insurance_claim_lines:
                    claim_in_db.update({'insurance_claim_line': insurance_claim_lines})
                else:
                    _logger.info("\n No claim line item present: %s", err)
                    raise UserError('NO claim line item present')
                    
                # Add history
                self._add_history(claim_in_db)
                    
            except Exception as err:
                _logger.info("\n Error Generating claim draft: %s", err)
                raise UserError(err)
    
    def _add_visit_specific_claim_line(self, claim_in_db, sale_order):
        _logger.debug("Inside _add_visit_specific_claim_line")
        odoo_product = ''
        hospital_type = sale_order.company_id.hospital_type
        if sale_order.care_setting == 'opd':
            ''' search for opd service product for hospital type.
                If PHC then OPD PHC 
                IF Hospital then OPD Hospital
                If product found (in imis_odoo_mapper) and its not a product in odoo. 
                then throw exception
                Add OPD service product for opd visit
            '''
            
            if hospital_type == 'PHC':
                odoo_product = 'OPD PHC'
            else:
                odoo_product = 'OPD Hospital'
                        
        elif sale_order.care_setting == 'emergency':
            ''' search for ER service product for hospital type.
                If PHC then ER PHC 
                IF Hospital then ER Hospital
                If product found (in imis_odoo_mapper) and its not a product in odoo. 
                then throw exception
                Add ER service product for ER visit
            '''

            if hospital_type == 'PHC':
                odoo_product = 'ER PHC'
            else:
                odoo_product = 'ER Hospital' 
                
        _logger.debug("odoo_product ->%s", odoo_product)
          
        if odoo_product:
            product = self.env['product.product'].search([('name', '=', odoo_product), ('active', '=', 'True')])
            if not product:
                raise UserError("%s is not a product in odoo"%(odoo_product))
            
            imis_mapped_row = self.env['insurance.odoo.product.map'].search([('odoo_product_id', '=', product.id), ('is_active', '=', 'True')])
            if imis_mapped_row is None or len(imis_mapped_row) == 0 :
                _logger.debug("imis_mapped_row mapping not found")
                raise UserError("%s is not mapped to insurance product"%(imis_product))
                            
            if len(imis_mapped_row) > 1 :
                _logger.debug("multiple mappings found")
                raise UserError("Multiple mappings found for %s"%(imis_product))
                                
            _logger.debug("imis_mapped_row ->%s", imis_mapped_row)
            claim_line_item = {
                'claim_id' : claim_in_db.id,
                'product_id' : imis_mapped_row.odoo_product_id.id,
                'product_qty' : 1,
                'product_uom' : imis_mapped_row.odoo_product_id.uom_id.id,
                'imis_product' : imis_mapped_row.id,
                'imis_product_code' : imis_mapped_row.item_code,
                'icd_code' :imis_mapped_row.icd_code.ipdCode,
                'price_unit' : imis_mapped_row.insurance_price,
                'currency_id': claim_in_db.currency_id
            }
            claim_line_in_db = self.env['insurance.claim.line'].create(claim_line_item)
            _logger.info(claim_line_in_db)  
                
    def _add_history(self, claim_in_db):
        # Add history
        claim_history_line = self.env['insurance.claim.history']._add_claim_history(claim_in_db)
                    
        claim_history = self.env['insurance.claim.history'].search([('claim_id', '=', claim_in_db.id)])
        if claim_history:
            claim_in_db.update({'insurance_claim_history': claim_history})   
    
    def _create_claim_line(self, claim, sale_order):
        _logger.info("Inside _create_claim_line")
        insurance_sale_order_lines = sale_order.order_line.filtered(lambda r: r.payment_type == 'insurance')
        if len(insurance_sale_order_lines) == 0 :
            raise UserError("No Sales order line marked as Insurance Payment type")
        
        for sale_order_line in insurance_sale_order_lines:
            _logger.info("Inside sale_order_line loop")
            imis_mapped_row = self.env['insurance.odoo.product.map'].search([('odoo_product_id', '=', sale_order_line.product_id.id), ('is_active', '=', 'True')])
            _logger.debug("imis_mapped_row ->%s", imis_mapped_row)
            
            if imis_mapped_row is None or len(imis_mapped_row) == 0 :
                _logger.debug("imis_mapped_row mapping not found")
                raise UserError("%s is not mapped to insurance product"%(sale_order_line.product_id.name))
            
            if len(imis_mapped_row) > 1 :
                _logger.debug("multiple mappings found")
                raise UserError("Multiple mappings found for %s"%(sale_order_line.product_id.name))
            
            #Check if a product is already present. If yes update quantity
            insurance_claim_line = claim.insurance_claim_line.filtered(lambda r: r.imis_product == imis_mapped_row.insurance_product)
        
            if insurance_claim_line:
                insurance_claim_line.update({'product_qty': insurance_claim_line + sale_order_line.product_uom_qty })
            else:
                self.create_new_claim_line(claim, sale_order_line, imis_mapped_row)
            
    def create_new_claim_line(self, claim, sale_order_line, imis_mapped_row):
        _logger.debug("Inside create_new_claim_line")
        claim_line_item = {
            'claim_id' : claim.id,
            'product_id' : sale_order_line.product_id.id,
            'product_qty' : sale_order_line.product_uom_qty,
            'product_uom' : sale_order_line.product_uom.id,
            'imis_product' : imis_mapped_row.id,
            'imis_product_code' : imis_mapped_row.item_code,
            'icd_code' :imis_mapped_row.icd_code.ipdCode,
            'price_unit' : imis_mapped_row.insurance_price,
            'currency_id': claim.currency_id
        }
        claim_line_in_db = self.env['insurance.claim.line'].create(claim_line_item)
        _logger.info(claim_line_in_db)
    
    def check_visit_closed(self, visit_uuid):
        #Check visit
        #get visit details
        return True
        response = self.env['insurance.connect']._get_visit(visit_uuid)
        if 'stopDateTime' in response:
            return True
        else:
            return False

    @api.multi
    def action_edit_fhir(self):
        _logger.info("Inside action_edit_fhir")
        if self.claim_code:
            params = self.env['insurance.fhir']._retrieve_claim_fhir(self.claim_code)
            claim_fhir_obj = self.env['insurance.fhir'].create(params)
            return {
                'type': 'ir.actions.act_window',
                'name': 'Insurance Fhir',
                'res_model': 'insurance.fhir',
                'view_type': 'form',
                'view_mode': 'form',
                'res_id': claim_fhir_obj.id,
                'view_id': self.env.ref('bahmni_insurance_odoo.insurance_fhir_edit_view', False).id,
                'target': 'new',
            }
        else:
            _logger.error("No Claim number")
            raise UserError("No Claim Id, Please update and retry !")

    @api.multi
    def action_view_eligibility(self):
        _logger.info("Inside action_view_eligibility")
        if self.nhis_number:
            partner_id = self.partner_id
            #params = self.env['insurance.eligibility'].get_insurance_details(partner_id)
            elig_response = self.env['insurance.eligibility'].get_insurance_details(partner_id)

            # ins_elg_obj = self.env['insurance.eligibility'].create(params)
            return {
                'type': 'ir.actions.act_window',
                'name': 'Eligibility Check',
                'res_model': 'insurance.eligibility',
                'view_type': 'form',
                'view_mode': 'form',
                'res_id': elig_response.id,
                'view_id': self.env.ref('bahmni_insurance_odoo.insurance_eligibility_check_result_view', False).id,
                'target': 'new',
            }
        else:
            _logger.info("No NHIS number")
            raise UserError("No Insuree Id, Please update and retry !")
    
    @api.multi
    def action_confirm(self):
        '''
            Confirm claim for submission
        ''' 
        _logger.debug("action_confirm")
        #check if state is draft or rejected
        for claim in self:
            _logger.debug(claim)
            # if self._check_if_eligible(claim) == False:
            #      raise UserError("Claim can't be processed. Claimed amount greater than eligible amount.")
            
            if self.check_visit_closed(claim.external_visit_uuid) == False:
                raise UserError("The current visit has not been closed. So can't be confirmed now.")
            
            
            # raise UserError("Action CUt")
            if claim.state in ('draft', 'rejected'):
                #Check if amount claimed is in the range of eligibility
                
                claim.update({
                    'state': 'confirmed'
                })
                
                self._add_history(claim)
                
                #Validation passes then confirm
                for claim_line in claim.insurance_claim_line:
                    _logger.info(claim_line)
                    if not claim_line.imis_product_code :
                        raise UserError("%s has no mapping present.Map the product and retry again."%(claim_line.product_id.name))
    
    @api.multi
    def action_claim_submit(self):
        '''
            Generate the claim number based on the range
            Change status to submitted
            Prepare json
            Submit the claim to insurance-integration
        '''
        _logger.info("action_claim_submit")
        #check if state is draft or rejected
        try:
            for claim in self:
                if claim.state == 'confirmed':
                    #Generate Claim Number
                    if claim.claim_code:
                        #Resubmission
                        _logger.info("Resubmission")
                        claim_code = claim.claim_code
                        
                        '''
                            Prepare Claim Code Base on Previous Submits
                            R -> Resubmit
                            RS -> Resubmited Second Time
                            RSS -> Resubmited Third Time
                            and so on
                        '''
                        
                        if "R" in claim_code:
                            claim_code.replace('R', 'S')
                        elif "S" in claim_code:
                            claim_code.replace('S', 'T')
                        elif "T" in claim_code:
                            claim_code.replace('T', 'F')
                        elif "RF" in claim_code:
                            claim_code.replace('RF', 'FF')
                        else:
                            claim_code = "R" + claim_code
                        
                    else:
                        _logger.info("Submission")
                        claim_code_setup_flag = self.env['insurance.config.settings']._get_claim_code_setup_option()
                        
                        _logger.info("claim_code_setup_flag=%s", claim_code_setup_flag)
                        
                        '''
                            Check if the claim code has been setup manually. If not then, use it from sequence
                        '''
                        if claim_code_setup_flag:
                            claim_code = self.env['insurance.config.settings']._get_next_value()
                        else:    
                            claim_code = self.env['ir.sequence'].next_by_code('insurance.claim.code')
                        
                        _logger.info("Claim Code=%s", claim_code)
                    
                    claim.update({
                        'claim_code':claim_code,
                        'state': 'submitted',
                        'claimed_date': fields.Datetime.now()
                    })
                    
                    self._add_history(claim)
                    claim_request = {
                        "patientUUID": claim.partner_uuid,
                        "visitUUID": claim.external_visit_uuid,
                        "claimId": claim.claim_code,
                        "insureeId": claim.nhis_number,
                        "total" : claim.claimed_amount_total,
                        "item": []
                    }
                    

                    if  claim.ipd_code:
                        claim_request['item'].append({
                                    "category": "item",
                                    "quantity": 1,
                                    "sequence": 1,
                                    "code": claim.ipd_code.insurance_product,
                                    "unitPrice": claim.ipd_code.insurance_price
                                })
                    else:
                        #Prepare Claim line item
                        sequence = 1
                        for claim_line in claim.insurance_claim_line:
                            if claim_line.imis_product_code :
                                claim_line.update({
                                    'claim_sequence': sequence
                                })
                                
                                if claim_line.product_id.product_tmpl_id.type.lower() == 'service':
                                    category = 'service'
                                else:
                                    category = 'item'
                                
                                claim_request['item'].append({
                                    "category": category,
                                    "quantity": claim_line.product_qty,
                                    "sequence": sequence,
                                    "code": claim_line.imis_product_code,
                                    "unitPrice": claim_line.price_unit
                                })
                                sequence += 1
                    _logger.debug(claim_request)
                    # raise UserError(claim_request)
            # Submit Claim for Processing
            response = self.env['insurance.connect']._submit_claims(claim_request)
            if response:
                self.update_claim_from_claim_response(claim, response)
                    
        except Exception as err:
            _logger.error(err)
            raise UserError(err)
    
    def update_claim_from_claim_response(self, claim, response):
        _logger.info("update_claim_from_claim_response")
        claim.amount_approved_total = response['approvedTotal']
        claim.rejected_reason = response['rejectionReason']
        claim.state = response["claimStatus"]
        # _logger.info(claim)

        for claim_response_line in response['claimLineItems']:
            _logger.info(json.dumps(claim_response_line))
            claim_line = self.env['insurance.claim.line'].search([('claim_sequence', '=', claim_response_line['sequence']), ('claim_id', '=', claim.id)])
            _logger.info(claim_response_line['sequence'])
            if claim_line:
                claim_line.update({
                    'state': claim_response_line['status']
                })

                claim_line.rejection_reason = claim_response_line['rejectedReason']
                claim_line.amount_approved = claim_response_line['totalApproved']
                claim_line.quantity_approved = claim_response_line['quantityApproved']
            else:
                raise UserError("The line item for current claim not found.")

    claim_code = fields.Char(string='Claim Code', help="Claim Code")
    claim_manager_id = fields.Many2one('res.users', string='Claims Manager', index=True, track_visibility='onchange', default=lambda self: self.env.user)
    claimed_date = fields.Datetime(string='Creation Date', index=True, help="Date on which claim is created.")
    claimed_received_date = fields.Datetime(string='Processed Date', index=True, help="Date on which claim is processed.")
    claimed_amount_total = fields.Monetary(string='Total Claimed Amount', store=True, readonly=True, compute=_claimed_amount_all)
    partner_id = fields.Many2one('res.partner', string='Insuree', required=True, change_default=True, index=True, track_visibility='always')
    nhis_number = fields.Char(related='partner_id.nhis_number', readonly=True, store=True, string='NHIS Number')
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env['res.company']._company_default_get('insurance.claim'))
    amount_approved_total = fields.Monetary(string='Total Approved Amount', store=True, compute=_claimed_amount_all)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('submitted', 'Submitted'),
        ('checked', 'Checked'),
        ('valuated', 'Valuated'),
        ('rejected', 'Rejected')
        ], string='Claim Status', default='draft', readonly=True)
    claim_comments = fields.Text(string='Comments')
    rejection_reason = fields.Text(string='Rejection Reason')
    insurance_claim_line = fields.One2many("insurance.claim.line", "claim_id", string='Claim Lines', states={'confirmed': [('readonly', True)], 'submitted': [('readonly', True)]}, copy=True)
    sale_orders = fields.Many2many('sale.order', string='Sale Orders')
    partner_uuid = fields.Char(related='partner_id.uuid', string='Customer UUID', store=True, readonly=True)
    currency_id = fields.Many2one(related='sale_orders.currency_id', string="Currency", readonly=True, required=True)
    insurance_claim_history = fields.One2many('insurance.claim.history', 'claim_id', string='Claim Lines', states={'confirmed': [('readonly', True)], 'submitted': [('readonly', True)], 'rejected': [('readonly', True)]}, copy=True)
    external_visit_uuid = fields.Char(string="External Visit Id", help="This field is used to store visit id of patient")
    ipd_code = fields.Many2one('insurance.odoo.product.map', string='IPD Package' )
    
    
class claims_line(models.Model):
    _name = 'insurance.claim.line'
    _description = 'Claim Line Items' 
    
    @api.depends('product_id')
    def _get_imis_product_code(self):
        _logger.info("Inside _get_imis_product_code")
        product_id = self.product_id.id
        insurance_product_mapper = self.env['insurance.odoo.product.map'].search([('odoo_product_id' , '=', product_id), ('is_active', '=', 'True')])
        _logger.info(insurance_product_mapper)
        if insurance_product_mapper:
            self.imis_product = insurance_product_mapper
            self.imis_product_code = insurance_product_mapper.imis_product_code
            self.price_unit = insurance_product_mapper.insurance_price
        else:
            raise UserError("This product has no mapping for insurance products")  
        
    @api.depends('product_id')
    def _get_unit_price(self):
        """
        Get unit price of the ite,
        """
        _logger.info("Inside _get_unit_price")
        self.price_unit = self.product_id.insurance_price
    
    @api.depends('product_qty', 'price_unit', 'product_uom')
    def _compute_amount(self):
        """
        Compute the amounts of the Claim line Item.
        """
        _logger.info("Inside _amount_all")
        self.price_total = self.price_unit * self.product_qty

    

        
    claim_id = fields.Many2one('insurance.claim', string='Claim ID', required=True, ondelete='cascade', index=True, copy=False)
    claim_manager_id = fields.Many2one(related='claim_id.claim_manager_id', store=True, string='Claims Manager', readonly=True)
    claim_partner_id = fields.Many2one(related='claim_id.partner_id', store=True, string='Customer')
    product_id = fields.Many2one('product.product', string='Product', domain=[('sale_ok', '=', True)], change_default=True, ondelete='restrict', required=True)
    imis_product = fields.Many2one('insurance.odoo.product.map', string='Insurance Item', change_default=True, required=True)
    icd_code = fields.Char( string='ICD CODE')
    imis_product_code = fields.Char(string='Product', change_default=True, required=True)
    product_qty = fields.Float(string='Quantity', required=True, default=1.0)
    product_uom = fields.Many2one('product.uom', string='Unit of Measure', required=True)
    price_unit = fields.Float(string='Unit Price', required=True, default=0.0)
    price_total = fields.Monetary(compute=_compute_amount, string='Total', readonly=True, store=True)
    amount_approved = fields.Monetary(string='Approved amount', store=True)
    currency_id = fields.Many2one(related='claim_id.currency_id', string="Currency", readonly=True, required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('passed', 'Passed'),
        ('rejected', 'Rejected')
        ],  string='Claim Status', readonly=True, copy=False, store=True)
    claim_comments = fields.Text(string='Comments')
    rejection_reason = fields.Text(string='Rejection Reason')
    claim_sequence = fields.Integer(string='Sequence', readonly=True)
    quantity_approved = fields.Integer(string='Quantity Approved', store=True)
    
    
class claim_history(models.Model):
    _name = 'insurance.claim.history'
    _description = 'Claim History'
    
    @api.model
    def _add_claim_history(self, claim):
        _logger.info("Inside _add_claim_history")
        claim_history = {
            'claim_id' : claim.id,
            'partner_id' : claim.partner_id.id,
            'claim_manager_id' : claim.claim_manager_id.id,
            'claim_code' : claim.claim_code,
            'state' : claim.state,
            'claim_comments': claim.claim_comments,
            'rejection_reason' : claim.rejection_reason
        }
        
        
        _logger.info(claim_history)
        
        return self.env['insurance.claim.history'].create(claim_history)

    claim_id = fields.Many2one('insurance.claim', string='Claim ID', required=True, ondelete='cascade', index=True, copy=False)
    partner_id = fields.Many2one(related='claim_id.partner_id', string='Insuree', readonly=True, required=True, change_default=True, index=True, track_visibility='always')
    claim_manager_id = fields.Many2one(related='claim_id.claim_manager_id', store=True, string='Claims Manager', readonly=True)
    claim_code = fields.Char( store=True, string='Claim Code')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('submitted', 'Submitted'),
        ('checked', 'Checked'),
        ('valuated', 'Valuated'),
        ('rejected', 'Rejected'),
        ('processed', 'Processed'),
        ('passed', 'Passed')

    ], string='Claim Status', readonly=True, copy=False, store=True, default='draft')
    claim_comments = fields.Text(store=True, string='Claim Comments')
    rejection_reason = fields.Text( store=True, string='Rejection Reason')
