"""Three opt-in pre2026 source profiles; original owner does all accounting.



The exact old source snapshot is executed once. Only its statement dispatch and

literal common-class predicates are extended in a private namespace. Old profile

names retain the old behavior. No prices, account outcomes or model inputs here.

"""

from __future__ import annotations

import ast

import copy

import hashlib

import importlib.util

import json

import re

import sys

from decimal import Decimal

from pathlib import Path

from types import FunctionType, SimpleNamespace

import pandas as pd

from scripts.research.a2.data import joint_cash_bindings as cash



BASE_SOURCE_REF = dict(path=r"D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\source_custody\reused_pair_cash_source_399ab875.py", sha256="399ab875a7ed88caf2961fb7645aae333bfdc0d0b2463a310571f3820df11c00")

CASH_SHA = "3aafa77d7637e08032041d884bbd8ad03f6c7fe5e5d08996c51c3a87fa7b7398"

MONETARY_COMMON = "SEC_ORIGINAL_MONETARY_COMMON_SINGLE_DECLARATION_R7"

CURRENT_PRIOR_ANNUAL = "SEC_ORIGINAL_CURRENT_PRIOR_ANNUAL_CASH_DECLARATION_R7"

EXACT_COMMON_CLASS = "SEC_ORIGINAL_DATED_FROZEN_COMMON_CLASS_DECLARATION_R7"

CLASS_A_CONVERSION_CONTEXT = "SEC_ORIGINAL_CLASS_A_CASH_WITH_OTHER_CLASS_CONVERSION_CONTEXT_R8"

WORDED_TRANSFER_RECORD = "SEC_ORIGINAL_WORDED_DOLLAR_TRANSFER_RECORD_QUARTERLY_COMMON_R8"

EQUAL_NAMED_COMMON_CLASSES = "SEC_ORIGINAL_META_SINGLE_AMOUNT_FOR_EXPLICIT_CLASS_A_AND_B_COMMON_R9"

META_NAMED_COMMON_SCOPE = {'schema': 'CONSENSUS_EXACT_META_2024_02_21_NAMED_COMMON_CASH_SOURCE_SCOPE_R9', 'ticker': 'META', 'sec_filer_cik': 1326801, 'ex_date': '2024-02-21', 'prior_date': '2024-02-20', 'record_date': '2024-02-22', 'pay_date': '2024-03-26', 'original_CUSIP': '30303M102', 'raw_accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.META', 'actual_accepted_at_utc': '2024-02-01T21:10:29+00:00', 'source_statement_sha256': '3d677938ac5823838a1e58c9b0c27265dc50740c8c4e7e40a5a8453deaa1d3c7', 'full_submission_ref': {'path': 'D:\\us-tech-quant-cache\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\static_sec_events\\1326801\\0001326801-24-000010\\0001326801-24-000010.txt', 'sha256': '2e3775eb5753c33ac7979a37dbc09e481153fdd71df2688ea60eb03ef472030b'}, 'original_source_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\META_ORIGINAL_NAMED_COMMON_CASH_LITERAL_AND_UID_PROOF_R9.json', 'sha256': '5ccff76529b17b58dbefe44a4adedc1c74b818442ad37e44e6989865be8fd24c'}}

ELV_CURRENT_COMMON = 'ELV_EXACT_2025_12_05_CURRENT_COMMON_DECLARED_XBRL_UNIT_AND_ORIGINAL_EX99_QUARTER_LITERAL_R14'

ELV_CURRENT_SCOPE=dict(profile=ELV_CURRENT_COMMON,ticker='ELV',ex_date='2025-12-05',prior_date='2025-12-04',record_date='2025-12-05',pay_date='2025-12-19',declaration_date='2025-10-15',issuer_CIK=1156039,original_CUSIP='036752103',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.ELV',original_listing_literal='Common Stock, Par Value $0.01 ELV NYSE',current_amount_literal='1.71',original_EX99_literal='Quarterly Dividend On October 15, 2025, the Audit Committee of the Company’s Board of Directors declared a fourth quarter 2025 dividend to shareholders of $1.71 per share. The fourth quarter dividend is payable on December 19, 2025, to shareholders of record at the close of business on December 5, 2025.',current_subject_proof_ref=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\ELV_EXACT_CURRENT_COMMON_DIVIDEND_USD_SOURCE_PROOF_R14_R2.json',sha256='ba23e4a341b60ed2ded3377d612141fe0f17c25affd6fcf9be7acd4d97a2fb41'),share_quantity_effect=False,old_default_venue_and_common_statement_rules_unchanged=True)



BAC_CURRENT_PERCENT = 'BAC_EXACT_2023_08_31_ONE_CURRENT_COMMON_QUARTER_CASH_AND_NONMONETARY_NINE_PERCENT_R16'

BAC_PERCENT_SCOPE=dict(profile=BAC_CURRENT_PERCENT,ticker='BAC',ex_date='2023-08-31',prior_date='2023-08-30',record_date='2023-09-01',pay_date='2023-09-29',declaration_date='2023-07-19',issuer_CIK=70858,original_CUSIP='060505104',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.BAC',publication_accepted_at_utc='2023-07-31T20:49:57+00:00',original_current_literal='On July 19, 2023, the Corporation’s Board of Directors (the Board) declared a quarterly common stock dividend of $0.24 per share, an increase of nine percent compared to the prior dividend rate, payable on September 29, 2023 to shareholders of record as of September 1, 2023.',source_role_proof_ref=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\BAC_EXACT_2023_08_31_CURRENT_ONE_CASH_NINE_PERCENT_SOURCE_ROLE_PROOF_R16_R1.json',sha256='3ef12c89021d41115b44f22efcbfdf0931072e5b8c87febce61bf3f17bf8356e'),share_quantity_effect=False,old_generic_MONETARY_no_comparison_rule_unchanged=True)



QCOM_CURRENT_POLICY = 'QCOM_EXACT_2024_05_30_CURRENT_ANNOUNCED_COMMON_CASH_AFTER_SAME_PARAGRAPH_QUARTER_POLICY_R17'

QCOM_POLICY_SCOPE = {'profile': 'QCOM_EXACT_2024_05_30_CURRENT_ANNOUNCED_COMMON_CASH_AFTER_SAME_PARAGRAPH_QUARTER_POLICY_R17', 'ticker': 'QCOM', 'ex_date': '2024-05-30', 'prior_date': '2024-05-29', 'issuer_CIK': 804328, 'original_CUSIP': '747525103', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.QCOM', 'record_date': '2024-05-30', 'pay_date': '2024-06-20', 'policy_announcement_date': '2024-03-05', 'quarterly_policy_effective_after_date': '2024-03-21', 'current_cash_announcement_date': '2024-04-17', 'publication_accepted_at_utc': '2024-05-01T20:06:32+00:00', 'original_current_literal': 'Dividends. On March 5, 2024, we announced an increase in our quarterly dividend per share of common stock from $ 0.80 to $ 0.85 , which is effective for dividends payable after March 21, 2024. On April 17, 2024 , we announced a cash dividend of $ 0.85 per share on our common stock, payable on June 20, 2024 to stockholders of record as of the close of business on May 30, 2024 .', 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\QCOM_EXACT_MAY_CURRENT_ANNOUNCED_QUARTER_POLICY_SOURCE_ROLE_PROOF_R17_R1.json', 'sha256': '64b9957ae3065d1f451cf362089c5aa8a5caf243ca3763ec25091a9c48ba15eb'}, 'share_quantity_effect': False, 'old_generic_profiles_unchanged': True}



PRMB_CURRENT_CLASS_A = 'PRMB_EXACT_2025_11_25_ORIGINAL_CLASS_A_COM_SHS_AND_CURRENT_CLASSA_DECLARED_USD_QUARTER_PRESS_R18'

KBR_CURRENT_COMMON = 'KBR_EXACT_2024_03_14_ORIGINAL_PRIOR_CURRENT_PERCENT_AND_INDEPENDENT_CURRENT_COMMON_CASH_R18'

PRMB_CURRENT_SCOPE = {'profile': 'PRMB_EXACT_2025_11_25_ORIGINAL_CLASS_A_COM_SHS_AND_CURRENT_CLASSA_DECLARED_USD_QUARTER_PRESS_R18', 'ticker': 'PRMB', 'ex_date': '2025-11-25', 'prior_date': '2025-11-24', 'issuer_CIK': 2042694, 'original_CUSIP': '741623102', 'original_frozen_class_literal': 'CLASS A COM SHS', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.PRMB', 'record_date': '2025-11-25', 'pay_date': '2025-12-05', 'board_declaration_date': '2025-11-05', 'press_publication_date': '2025-11-06', 'current_amount_literal': '0.10', 'proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\PRMB_EXACT_CURRENT_CLASS_A_CASH_USD_SOURCE_BINDING_PROOF_R18_R1.json', 'sha256': 'db103b813ab664619ff4c516dd72b2e82cc13fafb65398f92cc9829a8a6c77fb'}, 'publication_date': '2025-11-06', 'original_current_literal': 'QUARTERLY DIVIDEND Primo Brands announced that its Board of Directors declared a dividend of $0.10 per share on the outstanding common stock of the Company, payable on December 5, 2025, in cash, to the holders of record of such common stock of the Company at the close of business on November 25, 2025. ABOUT PRIMO BRANDS CORPORATION Primo Brands is a leading North American branded beverage company focused on healthy hydration, delivering responsibly sourced diversified offerings across products, formats, channels, price points, and consumer occasions, distributed in every U.S. state and Canada. Primo Brands has a comprehensive portfolio of highly recognizable and conveniently packaged branded water and beverages that reach consumers whenever, wherever, and however they hydrate through distribution across retail outlets, away from home such as hotels and hospitals, and hospitality and food service accounts, as well as direct delivery to homes and businesses. These brands include established “billion-dollar brands” Poland Spring® and Pure Life®, premium brands like Saratoga® and The Mountain Valley®, leading regional spring water offerings such as Arrowhead®, Deer Park®, Ice Mountain®, Ozarka®, and Zephyrhills®, purified water brands including Primo Water® and Sparkletts®, and flavored and enhanced beverages like Splash Refresher™ and AC+ION®. Primo Brands also has an industry-leading line-up of innovative water dispensers, which create consumer connectivity through recurring water purchases. Primo Brands operates a vertically integrated coast-to-coast network that distributes its brands to more than 200,000 retail outlets, as well as directly reaching customers and consumers through its Direct Delivery, Exchange and Refill offerings. Through Direct Delivery, Primo Brands delivers responsibly sourced hydration solutions direct to home and business customers. Through its Exchange business, consumers can visit approximately 26,500 retail locations and purchase a pre-filled, multi-use bottle of water that can be exchanged after use for a discount on the next purchase. Through its Refill business, consumers have the option to refill empty multi-use bottles at approximately 23,500 self-service refill stations. Primo Brands also offers water filtration units for home and business customers across North America. Primo Brands is a leader in reusable beverage packaging, helping to reduce waste through its multi-serve bottles and innovative brand packaging portfolio, which includes recycled plastic, aluminum, and glass. Primo Brands has a portfolio of over 80 springs and actively manages water resources to help assure a steady supply of quality, safe drinking water today and in the future. Primo Brands also helps conserve over 28,000 acres of land across the U.S. and Canada. Primo Brands is proud to partner with the International Bottled Water Association ("IBWA") in North America, which supports strict adherence to safety, quality, sanitation, and regulatory standards for the benefit of consumer protection. Primo Brands is committed to supporting the communities it serves, investing in local and national programs and delivering hydration solutions following natural disasters and other local community challenges. Primo Brands employs more than 12,000 associates with dual headquarters in Tampa, Florida, and Stamford, Connecticut. For more information, please visit www.primobrands.com. 4', 'original_fragment_sha256': 'dc35f1181ed6900b2026b864178ef3ccb9ca4a92c7822d13f5d37eaef21edb28'}

KBR_CURRENT_SCOPE = {'profile': 'KBR_EXACT_2024_03_14_ORIGINAL_PRIOR_CURRENT_PERCENT_AND_INDEPENDENT_CURRENT_COMMON_CASH_R18', 'ticker': 'KBR', 'ex_date': '2024-03-14', 'prior_date': '2024-03-13', 'issuer_CIK': 1357615, 'original_CUSIP': '48242W106', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.KBR', 'record_date': '2024-03-15', 'pay_date': '2024-04-15', 'board_declaration_date': '2024-02-19', 'publication_date': '2024-02-20', 'current_amount_literal': '0.15', 'proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\KBR_EXACT_PRIOR_CURRENT_COMMON_TWO_SOURCE_BINDING_PROOF_R18_R1.json', 'sha256': '51902bfef40285063d174fbe33b49a16bb1454d1e90360014c9c48c1a90fa802'}, 'original_current_literal': 'On February 19, 2024, the Board of Directors approved an increase of our quarterly regular dividend from $0.135 per share to $0.15 per share effective for the record date and payment date of the next scheduled distribution on March 15, 2024 and April 15, 2024, respectively. This represents the fifth successive year of dividend increases, representing an 11% increase from the previous regular dividend amount.', 'original_fragment_sha256': '525634512ced4e1298c82c89c2109d7330b07a25128d5cf86aa519d511f2c6e3'}

AMAT_HTML_ONE_SCOPE = {'profile': 'AMAT_EXACT_2025_08_21_ORIGINAL_APPROVED_QUARTER_COMMON_CASH_WITH_PRIOR_POLICY_AND_SEPARATE_USD_UNIT_R18', 'material_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\AMAT_EXACT_CURRENT_ORIGINAL_ARCHIVE_COMMON_USD_SOURCE_BINDING_PROOF_R18_R2.json', 'sha256': '4cdf40ac7f54940fe7961be756a82da45b30a853e2eca227110308fa0638d23c'}, 'exact_ex_dates': ['2025-08-21'], 'ticker': 'AMAT', 'issuer_cik': 6951, 'original_CUSIP': '038222105', 'old_source_profiles_unchanged': True, 'alpha_or_label_expansion': False}

AMAT_UNIT_SUPPORT_SCHEMA='AMAT_ONE_ORIGINAL_PREEX_COMMON_USD_SHARE_UNIT_SUPPORT_R18'



APO_FIRST_QUARTER = 'APO_EXACT_2024_05_16_ORIGINAL_CURRENT_COMMON_FIRST_QUARTER_CASH_R19'

APO_FIRST_QUARTER_SCOPE = {'profile': 'APO_EXACT_2024_05_16_ORIGINAL_CURRENT_COMMON_FIRST_QUARTER_CASH_R19', 'ticker': 'APO', 'ex_date': '2024-05-16', 'prior_date': '2024-05-15', 'issuer_CIK': 1858681, 'original_CUSIP': '03769M106', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.APO', 'record_date': '2024-05-17', 'pay_date': '2024-05-31', 'source_publication_date': '2024-05-02', 'publication_accepted_at_utc': '2024-05-02T10:31:01+00:00', 'quarter_ended_date': '2024-03-31', 'current_amount_literal': '0.4625', 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\APO_ONE_EXACT_FIRST_QUARTER_COMMON_SOURCE_ROLE_PROOF_R19_R2.json', 'sha256': 'af7ec40fa5a2f9b22ec387e82bc0b6250dac7b9a88ca20639f759a4a3ee9adf1'}, 'original_current_literal': 'Apollo Global Management, Inc. has declared a cash dividend of $0.4625 per share of its Common Stock for the first quarter ended March 31, 2024. This dividend will be paid on May 31, 2024 to holders of record at the close of business on May 17, 2024.', 'original_current_fragment_sha256': '8666724638bc576400b95be33d66ddf99922d148f583c0ffdf01857ec2debc72'}

RECORD_PAYABLE_CURRENT_COMMON = 'SEC_EXACT_CURRENT_COMMON_RECORD_DATE_PAYABLE_CONTEXT_R24'

RECORD_PAYABLE_COMMON_SCOPES = {'LPLA|2024-11-14': {'profile': 'SEC_EXACT_CURRENT_COMMON_RECORD_DATE_PAYABLE_CONTEXT_R24', 'ticker': 'LPLA', 'ex_date': '2024-11-14', 'prior_date': '2024-11-13', 'issuer_CIK': 1397911, 'original_CUSIP': '50212V100', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.LPLA', 'listing_identity': 'NASDAQ:LPLA', 'record_date': '2024-11-14', 'pay_date': '2024-12-02', 'source_publication_date': '2024-11-04', 'publication_accepted_at_utc': '2024-11-04T21:18:42+00:00', 'accession': '0001397911-24-000141', 'current_amount_literal': '0.30', 'original_current_literal': 'The Board declared a cash dividend of $ 0.30 per share on LPLFH’s outstanding common stock to be paid on December 2, 2024 to all stockholders of record on November 14, 2024 .', 'original_money_tokens': ['0.30'], 'current_context_ref': 'c-457', 'current_context_role': 'RECORD_DATE_NOT_ANNOUNCEMENT_DATE', 'current_context_instant': '2024-11-14', 'quarter_member': 'lpla:O2024Q3DividendsMember', 'current_amount_concept': 'us-gaap:DividendsPayableAmountPerShare', 'exact_board_day_inferred': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\LPLA_ONE_EXACT_CURRENT_RECORD_PAYABLE_CONTEXT_SOURCE_ROLE_PROOF_R24_R1.json', 'sha256': 'd360fafefff1715d80274f3b937633f32454978bc4a548b4cab598d1b1b0b8fa'}}}



CLASS_PROFILES = (EXACT_COMMON_CLASS, CLASS_A_CONVERSION_CONTEXT, EQUAL_NAMED_COMMON_CLASSES, PRMB_CURRENT_CLASS_A)

QCOM_CURRENT_CONTEXT = 'QCOM_EXACT_CURRENT_ANNOUNCED_COMMON_SUBSEQUENT_QUARTER_CONTEXT_R20'

QCOM_CONTEXT_SCOPES = {'2025-03-06': {'profile': 'QCOM_EXACT_CURRENT_ANNOUNCED_COMMON_SUBSEQUENT_QUARTER_CONTEXT_R20', 'ticker': 'QCOM', 'ex_date': '2025-03-06', 'prior_date': '2025-03-05', 'issuer_CIK': 804328, 'original_CUSIP': '747525103', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.QCOM', 'record_date': '2025-03-06', 'pay_date': '2025-03-27', 'source_publication_date': '2025-02-05', 'publication_accepted_at_utc': '2025-02-05T21:05:57+00:00', 'accession': '0000804328-25-000011', 'current_announcement_date': '2025-01-17', 'current_context_ref': 'c-50', 'quarter_member': 'qcom:O2025Q2DividendsMember', 'current_amount_literal': '0.85', 'original_current_literal': 'Dividends. On January 17, 2025 , we announced a cash dividend of $ 0.85 per share on our common stock, payable on March 27, 2025 to stockholders of record as of the close of business on March 6, 2025 .', 'original_money_tokens': ['0.85'], 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\QCOM_2025-03-06_EXACT_CURRENT_QUARTER_CONTEXT_SOURCE_ROLE_PROOF_R20_R1.json', 'sha256': '424e9dd00af1769d9e7e779328353ab4ef9e61b1dca8e7f9d7a96b2932969e1f'}}, '2025-06-05': {'profile': 'QCOM_EXACT_CURRENT_ANNOUNCED_COMMON_SUBSEQUENT_QUARTER_CONTEXT_R20', 'ticker': 'QCOM', 'ex_date': '2025-06-05', 'prior_date': '2025-06-04', 'issuer_CIK': 804328, 'original_CUSIP': '747525103', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.QCOM', 'record_date': '2025-06-05', 'pay_date': '2025-06-26', 'source_publication_date': '2025-04-30', 'publication_accepted_at_utc': '2025-04-30T20:05:23+00:00', 'accession': '0000804328-25-000031', 'current_announcement_date': '2025-04-18', 'current_context_ref': 'c-83', 'quarter_member': 'qcom:O2025Q3DividendsMember', 'current_amount_literal': '0.89', 'original_current_literal': 'Dividends. On March 18, 2025, we announced an increase in our quarterly dividend per share of common stock from $ 0.85 to $ 0.89 , which is effective for dividends payable after March 27, 2025. On April 18, 2025 , we announced a cash dividend of $ 0.89 per share on our common stock, payable on June 26, 2025 to stockholders of record as of the close of business on June 5, 2025 .', 'original_money_tokens': ['0.85', '0.89', '0.89'], 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\QCOM_2025-06-05_EXACT_CURRENT_QUARTER_CONTEXT_SOURCE_ROLE_PROOF_R20_R1.json', 'sha256': '15e3c5f016d60cb75857399d5219c5f46094565e6511d08681483ff3079308b1'}}}



NAMED_AB_CURRENT = 'EXACT_TWO_NAMED_A_B_EQUAL_CURRENT_COMMON_QUARTER_CASH_R21'

NAMED_AB_SCOPES = {'FCNCA|2023-11-29': {'profile': 'EXACT_TWO_NAMED_A_B_EQUAL_CURRENT_COMMON_QUARTER_CASH_R21', 'ticker': 'FCNCA', 'ex_date': '2023-11-29', 'prior_date': '2023-11-28', 'issuer_CIK': 798941, 'original_CUSIP': '31946M103', 'accounting_sid': 'SOURCE_ISSUER_COMMON_CLASS:8f80e8fde715d99d8f5783939d45cad40ef2eeae3c566d5dbdbb507e305f401c', 'record_date': '2023-11-30', 'pay_date': '2023-12-15', 'declaration_date': '2023-10-24', 'source_publication_date': '2023-11-03', 'publication_accepted_at_utc': '2023-11-03T13:12:50+00:00', 'accession': '0000798941-23-000048', 'listing_identity': 'NASDAQ:FCNCA', 'original_current_literal': 'During the first, second and third quarters of 2023, we paid a quarterly dividend of $0.75 on the Class A Common Stock and Class B Common Stock. On October 24, 2023, our Board of Directors declared a quarterly dividend on the Class A Common Stock and Class B Common Stock of $1.64 per common share, an increase of 219% from the prior quarter distribution. The dividends are payable on December 15, 2023 to stockholders of record as of November 30, 2023.', 'current_amount_literal': '1.64', 'original_money_tokens': ['0.75', '1.64'], 'original_percent_tokens': ['219'], 'original_frozen_class': 'CL A', 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\FCNCA_2023-11-29_EXACT_NAMED_A_B_CURRENT_SOURCE_ROLE_PROOF_R21_R1.json', 'sha256': 'f1a3ec0312b220cb7aa75a25412eb7d943d4376a8f9c7be2349f96c4365b7abb'}}, 'MA|2024-04-08': {'profile': 'EXACT_TWO_NAMED_A_B_EQUAL_CURRENT_COMMON_QUARTER_CASH_R21', 'ticker': 'MA', 'ex_date': '2024-04-08', 'prior_date': '2024-04-05', 'issuer_CIK': 1141391, 'original_CUSIP': '57636Q104', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.MA', 'record_date': '2024-04-09', 'pay_date': '2024-05-09', 'declaration_date': '2024-02-06', 'source_publication_date': '2024-02-13', 'publication_accepted_at_utc': '2024-02-13T17:47:32+00:00', 'accession': '0001141391-24-000022', 'listing_identity': 'NYSE:MA', 'original_current_literal': 'On February 6, 2024, our Board of Directors declared a quarterly cash dividend of $0.66 per share payable on May 9, 2024 to holders of record on April 9, 2024 of our Class A common stock and Class B common stock. The aggregate amount of this dividend is estimated to be $616 million.', 'current_amount_literal': '0.66', 'original_money_tokens': ['0.66', '616'], 'original_percent_tokens': [], 'original_frozen_class': 'CL A', 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\MA_2024-04-08_EXACT_NAMED_A_B_CURRENT_SOURCE_ROLE_PROOF_R21_R1.json', 'sha256': '977d09a6026951979e4db0beac435ee067d544bc7a3d077e8b4e22a42ac1aeab'}}}

CLASS_PROFILES += (NAMED_AB_CURRENT,)



ORDINAL_CURRENT_COMMON = 'SEC_EXACT_CURRENT_ORDINAL_QUARTER_COMMON_DECLARED_MONTH_CONTEXT_R22'

ORDINAL_COMMON_SCOPES = {'BBWI|2024-06-07': {'profile': 'SEC_EXACT_CURRENT_ORDINAL_QUARTER_COMMON_DECLARED_MONTH_CONTEXT_R22', 'ticker': 'BBWI', 'ex_date': '2024-06-07', 'prior_date': '2024-06-06', 'issuer_CIK': 701985, 'original_CUSIP': '070830104', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.BBWI', 'record_date': '2024-06-07', 'pay_date': '2024-06-21', 'source_publication_date': '2024-06-04', 'publication_accepted_at_utc': '2024-06-04T20:55:29+00:00', 'accession': '0000701985-24-000018', 'listing_identity': 'NYSE:BBWI', 'current_month_precision': '2024-05', 'current_context_ref': 'c-65', 'current_context_start_date': '2024-05-01', 'current_context_end_date': '2024-05-31', 'current_ordinal_quarter_literal': 'second quarter 2024 ordinary dividend', 'current_amount_literal': '0.20', 'original_current_literal': 'In May 2024, the Company declared its second quarter 2024 ordinary dividend of $ 0.20 per share payable on June 21, 2024 to stockholders of record at the close of business on June 7, 2024.', 'original_money_tokens': ['0.20'], 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\BBWI_ONE_CURRENT_ORDINAL_COMMON_MONTH_CONTEXT_ROLE_PROOF_R22_R1.json', 'sha256': '425f2a8560abf88fa7878aecabacb12dd129dd0c22d3b3212a795a4482bf9016'}}}



PROFILES = (MONETARY_COMMON, CURRENT_PRIOR_ANNUAL, EXACT_COMMON_CLASS, CLASS_A_CONVERSION_CONTEXT, WORDED_TRANSFER_RECORD, EQUAL_NAMED_COMMON_CLASSES, ELV_CURRENT_COMMON, BAC_CURRENT_PERCENT, QCOM_CURRENT_POLICY, PRMB_CURRENT_CLASS_A, KBR_CURRENT_COMMON, APO_FIRST_QUARTER, QCOM_CURRENT_CONTEXT, NAMED_AB_CURRENT, ORDINAL_CURRENT_COMMON, RECORD_PAYABLE_CURRENT_COMMON)

SCOPE = dict(schema="CONSENSUS_CASH_SOURCE_PROFILE_COMPLETION_R9", profiles=list(PROFILES),

    base_owner_ref=BASE_SOURCE_REF, scope_end_exclusive="2026-01-01", accounting_only=True,

    old_profiles_unchanged=True, original_class_and_SID_rewritten=False,

    source_byte_transport_and_numeric_adjudication_unchanged=True, strict_PIT=False,

    explicit_new_profile_clock_consumer=True, cash_base_sha256=CASH_SHA,

    cns_notice_extension="EXACT_A9503_2024_PLUS_ORIGINAL_A9648_2025_NO_GENERIC_CALENDAR_CHANGE")

SCOPE['exact_dated_archive_profiles']=[AMAT_HTML_ONE_SCOPE['profile']]

OLD_STATIC = "STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION"

AAPL_CNS_STATIC_SCOPE=dict(schema='CONSENSUS_EXACT_AAPL_STATIC_COMMON_A9503_CNS_SOURCE_PROFILE_R7',

    profile='AAPL_2024_11_08_STATIC_COMMON_AND_A9503_CNS_OPT_IN',ticker='AAPL',sec_filer_cik=320193,

    accession='0000320193-24-000120',original_source_candidate_index=209,

    full_submission_sha256='6710cd44788282582e338c7782826cef3552a04615dc94a94d404463948e8e50',

    record_date='2024-11-11',pay_date='2024-11-14',projected_ex_date='2024-11-08',

    scope_end_exclusive='2026-01-01',clock_role='POST_VERIFIED_ACCOUNTING_ONLY',available_at=None,

    actual_exchange_ex_authority='UNKNOWN',strict_PIT=False,share_quantity_effect=False,

    old_STATIC_without_opt_in_unchanged=True,original_issuer_record_date_preserved=True)



_BASE = None



def _require(value, reason):

    if not value: raise ValueError(reason)



def _ref(path):

    path=Path(path)

    with path.open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()

    return dict(path=str(path),sha256=sha)



def _path_sha_ref(value):

    """Canonical native ref projection; producer metadata remains in its custody."""

    _require(isinstance(value,dict) and all(isinstance(value.get(k),str) for k in ('path','sha256')),'CASH_NATIVE_PATH_SHA_REF_REQUIRED')

    return {k:value[k] for k in ('path','sha256')}



def _base():

    global _BASE

    _require(_ref(BASE_SOURCE_REF['path'])==BASE_SOURCE_REF,'R7_BASE_SOURCE_BYTES_CHANGED')

    if _BASE is None:

        name='scripts.research.a2.data._consensus_cash_source_original_399ab875'

        spec=importlib.util.spec_from_file_location(name,BASE_SOURCE_REF['path'])

        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)

        _BASE=module

    return _BASE



def __getattr__(name):

    if name.startswith('__'):raise AttributeError(name)

    return getattr(_base(),name)



def _extended_statement_semantics(profile,text,facts,publication,listed_common_class):

    """Two opt-in literal shapes; no other class receives a converted cash claim."""

    _require(profile in (CLASS_A_CONVERSION_CONTEXT,WORDED_TRANSFER_RECORD),'R8_UNPLANNED_LITERAL_PROFILE')

    _require(len(text)<=4096 and '\n' not in text,'R8_SINGLE_ORIGINAL_DECLARATION_REQUIRED')

    _require(len(re.findall(r'\b(?:declared|approved|declaration)\b',text,re.I))==1 and

        len(re.findall(r'\bdividends?\b',text,re.I))==1,'R8_SINGLE_DECLARATION_AND_ALL_AMOUNT_ROLES_REQUIRED')

    _require(not re.search(r'\b(?:adjusted|restated|special|liquidating|return of capital|stock dividend|paid in shares|in kind|ADR|ADS|depositary)\b',text,re.I),'R8_DIFFERENT_ECONOMIC_UNIT')

    dates=r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}'

    if profile==CLASS_A_CONVERSION_CONTEXT:

        _require(listed_common_class=='A','R8_EXACT_LISTED_CLASS_A_REQUIRED')

        context=r'(?:class B(?:-1)? and C common stock and series A, B and C convertible participating preferred stock|all other outstanding common and preferred stock)'

        pattern=(r'\bdeclared a quarterly cash dividend in the amount of \$\s*(\d+(?:\.\d+)?) per share of class A common stock '

            r'\((determined in the case of '+context+r' on an as-converted basis)\), payable on ('+dates+r'), to all holders of record as of ('+dates+r')\.')

        m=re.search(pattern,text,re.I)

        _require(m is not None,'R8_COMPLETE_CLASS_A_DECLARATION_AND_CONVERSION_CONTEXT_REQUIRED')

        _require(text.count('$')==1 and len(re.findall(r'\bpreferred\b',text,re.I))==1,'R8_ALL_MONEY_AND_OTHER_CLASS_CONTEXT_REQUIRED')

        current,pay,record=m.group(1),m.group(3),m.group(4)

        roles=[dict(role='CLASS_A_CURRENT_QUARTER_CASH_DECLARATION',literal=current,share_class='A')]

        details=dict(other_class_context_literal=m.group(2),other_class_context_role='SOURCE_AS_CONVERTED_CONTEXT_ONLY_NO_AMOUNT_OR_SHARE_AUTHORITY',other_class_cash_or_quantity_inferred=False,certified_cash_share_classes=['A'])

    else:

        _require(listed_common_class is None and not re.search(r'\b(?:Class\s+[A-Z]|preferred|convertible)\b',text,re.I),'R8_EXACT_UNCLASSIFIED_COMMON_SHARE_REQUIRED')

        pattern=(r'\bBoard of Directors declared an (\d+(?:\.\d+)?) percent increase in the quarterly dividend to '

            r'([a-z-]+) dollars? and ([a-z-]+(?: [a-z-]+)?) cents? \(\$(\d+(?:\.\d+)?)\) per share, payable ('+dates+r'), '

            r'to all holders of common stock as shown on the transfer records of the corporation at the close of business on ('+dates+r')\.')

        m=re.search(pattern,text,re.I)

        _require(m is not None,'R8_COMPLETE_WORDED_AMOUNT_AND_TRANSFER_RECORD_REQUIRED')

        small=dict(zero=0,one=1,two=2,three=3,four=4,five=5,six=6,seven=7,eight=8,nine=9,ten=10,eleven=11,twelve=12,thirteen=13,fourteen=14,fifteen=15,sixteen=16,seventeen=17,eighteen=18,nineteen=19,twenty=20,thirty=30,forty=40,fifty=50,sixty=60,seventy=70,eighty=80,ninety=90)

        def word_number(word):

            parts=re.split(r'[- ]',word.lower())

            _require(all(x in small for x in parts) and (len(parts)==1 or len(parts)==2 and small[parts[0]]>=20 and small[parts[0]]%10==0 and 1<=small[parts[1]]<=9),'R8_UNSUPPORTED_OR_AMBIGUOUS_WORDED_NUMBER')

            return sum(small[x] for x in parts)

        dollars,cents=word_number(m.group(2)),word_number(m.group(3));current,pay,record=m.group(4),m.group(5),m.group(6)

        _require(0<=cents<100 and Decimal(current)==Decimal(dollars)+Decimal(cents)/100,'R8_WORDED_AND_NUMERIC_AMOUNT_CONFLICT')

        _require(text.count('$')==1 and len(re.findall(r'\bdollars?\b',text,re.I))==1 and len(re.findall(r'\bcents?\b',text,re.I))==1,'R8_ALL_WORDED_AND_MONETARY_AMOUNTS_REQUIRED')

        roles=[dict(role='CURRENT_QUARTER_DECLARATION',literal=current,worded_amount_literal=m.group(2)+' dollar and '+m.group(3)+' cents')]

        details=dict(increase_percent_literal=m.group(1),increase_percent_role='DECLARATION_CHANGE_DESCRIPTION_NOT_PRIOR_CASH_OR_SHARE_RATIO',prior_amount_reconstructed=False,record_role='ISSUER_COMMON_HOLDERS_ON_TRANSFER_RECORDS_AT_CLOSE_OF_BUSINESS')

    _require(str(pd.Timestamp(pay).date())==facts['pay_date'] and str(pd.Timestamp(record).date())==facts['record_date'],'R8_LITERAL_DATES_CHANGED')

    _require(pd.Timestamp(publication)<pd.Timestamp('2026-01-01') and pd.Timestamp(publication)<=pd.Timestamp(facts['record_date']),'R8_PRE2026_SOURCE_CLOCK_REQUIRED')

    _require(Decimal(current)==Decimal(str(facts['cash_per_raw_share'])),'R8_CURRENT_AMOUNT_CHANGED')

    return dict(profile=profile,amount_roles=roles,selected_current_amount=current,record_date=facts['record_date'],pay_date=facts['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),cash_payment_basis='USD_PER_RAW_OLD_SHARE_AFTER_NATIVE_US_CHARTER_AND_EXACT_RAW_GATES',old_amounts_not_discarded=True,annual_rate_divided_or_inferred=False,original_text_not_rewritten=True,**details)



def _meta_statement_semantics(text,facts,publication,listed_common_class):

    """One real, byte-bound declaration; no class or amount is reconstructed."""

    src=META_NAMED_COMMON_SCOPE

    _require(listed_common_class=='A' and facts.get('ticker')==src['ticker'] and facts['record_date']==src['record_date'] and facts['pay_date']==src['pay_date'] and hashlib.sha256(text.encode()).hexdigest()==src['source_statement_sha256'],'R9_EXACT_REAL_META_SOURCE_LITERAL_AND_NAMED_CLASS_REQUIRED')

    _require(pd.Timestamp(publication)==pd.Timestamp('2024-02-01'),'R9_ACTUAL_SOURCE_ACCEPTANCE_DAY_REQUIRED')

    dates=r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}'

    m=re.search(r'\bboard of directors declared a cash dividend of \$\s*(\d+(?:\.\d+)?) per share of its outstanding Class A common stock and Class B common stock, payable on ('+dates+r') to stockholders of record as of the close of business on ('+dates+r')\.',text,re.I)

    _require(m is not None and text.count('$')==1 and {x.upper() for x in re.findall(r'\bClass\s+([A-Z])\b',text,re.I)}=={'A','B'} and not re.search(r'\b(?:preferred|converted|convertible|ADR|ADS)\b',text,re.I),'R9_FULL_ORIGINAL_SINGLE_AMOUNT_NAMED_COMMON_CLASSES_REQUIRED')

    _require(Decimal(m.group(1))==Decimal(str(facts['cash_per_raw_share'])) and str(pd.Timestamp(m.group(2)).date())==facts['pay_date'] and str(pd.Timestamp(m.group(3)).date())==facts['record_date'],'R9_ORIGINAL_MONEY_OR_DATES_CHANGED')

    return dict(profile=EQUAL_NAMED_COMMON_CLASSES,amount_roles=[dict(role='ONE_ORIGINAL_CASH_AMOUNT_EXPLICITLY_SHARED_BY_NAMED_COMMON_CLASSES',literal=m.group(1),source_common_classes=['A','B'],accounting_target_class='A')],selected_current_amount=m.group(1),record_date=facts['record_date'],pay_date=facts['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),cash_payment_basis='USD_PER_RAW_OLD_SHARE_AFTER_NATIVE_US_CHARTER_AND_EXACT_RAW_GATES',old_amounts_not_discarded=True,annual_rate_divided_or_inferred=False,original_text_not_rewritten=True,certified_source_cash_share_classes=['A','B'],certified_accounting_cash_share_classes=['A'],other_class_cash_or_quantity_inferred=False,other_class_account_position_created=False,real_original_source_proof_ref=copy.deepcopy(src['original_source_proof_ref']))



def _elv_statement_semantics(text,facts,publication,*,listed_common_class=None):

    scope=ELV_CURRENT_SCOPE

    _require(listed_common_class is None and text==scope['original_EX99_literal'] and facts.get('ticker')=='ELV' and facts.get('cash_per_raw_share')==1.71 and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and str(pd.Timestamp(publication).date())=='2025-10-21','R14_EXACT_UNMODIFIED_ELV_DECLARATION_CURRENT_AND_CLOCK_REQUIRED')

    _require(re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==['1.71'] and 'fourth quarter 2025 dividend' in text and text.startswith('Quarterly Dividend '),'R14_ORIGINAL_QUARTER_HEADING_AND_EXPLICIT_CURRENT_ONLY_REQUIRED')

    return dict(profile=ELV_CURRENT_COMMON,amount_roles=[dict(role='EXPLICIT_ORIGINAL_EX99_CURRENT_FOURTH_QUARTER_DECLARATION',literal='1.71')],selected_current_amount='1.71',record_date=facts['record_date'],pay_date=facts['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),cash_payment_basis='USD_PER_RAW_OLD_SHARE_AFTER_EXACT_CURRENT_COMMON_DECLARED_CONCEPT_AND_NATIVE_US_RAW_GATES',current_subject_proof_ref=scope['current_subject_proof_ref'],common_subject_role='EXACT_CURRENT_STATEMENT_COMMON_STOCK_DECLARED_XBRL_CONCEPT_NOT_COVER_INFERENCE',old_amounts_not_discarded=True,annual_rate_divided_or_inferred=False,current_amount_from_capital_row=False,original_text_not_rewritten=True)



def _elv_current_common_support(payload,entry,facts,listing,pinned):

    scope=ELV_CURRENT_SCOPE

    _require(payload.get('elv_exact_current_common_dividend_scope')==scope and payload.get('sec_cash_statement_profile')==ELV_CURRENT_COMMON and payload.get('sec_source_transport_profile')==_base().SEC_STATIC_SUBMISSION_PROFILE,'R14_EXACT_ELV_SCOPE_REQUIRED')

    _require(listing==scope['original_listing_literal'] and facts['ticker']=='ELV' and facts['sec_filer_cik']==1156039 and facts['security_id']==scope['accounting_sid'] and facts['listing_identity']=='NYSE:ELV' and facts['exact_frozen_event_key']['ticker']=='ELV' and facts['exact_frozen_event_key']['effective_date']==scope['ex_date'] and entry['prior_raw_close']['prior_date']==scope['prior_date'] and facts['record_date']==scope['record_date'] and facts['pay_date']==scope['pay_date'] and Decimal(str(facts['cash_per_raw_share']))==Decimal('1.71') and facts['available_at'] is None and facts['currency']=='USD' and facts['amount_unit']==cash.USD_PER_RAW_OLD_SHARE and facts['quantity_coordinate']==cash.RAW_OLD_SHARE_COORDINATE,'R14_EXACT_ELV_EVENT_RAW_UNIT_AND_ORIGINAL_VENUE_REQUIRED')

    proof=json.loads(pinned(scope['current_subject_proof_ref']).read_text(encoding='utf-8'));event=proof['event']

    _require(all(event[k]==scope[v] for k,v in [('ticker','ticker'),('ex_date','ex_date'),('prior_date','prior_date'),('issuer_CIK','issuer_CIK'),('original_CUSIP','original_CUSIP'),('accounting_sid','accounting_sid'),('record_date','record_date'),('pay_date','pay_date'),('board_declaration_date','declaration_date')]) and proof['current_common_declared_concept']=='us-gaap:CommonStockDividendsPerShareDeclared' and proof['current_amount_from_capital_or_paid_financial_rows'] is False and proof['first_publication_at'] is None and proof['engine_available_at'] is None and proof['historical_availability_authority']=='UNKNOWN','R14_EXACT_CURRENT_COMMON_DECLARED_PROOF_REQUIRED')

    ex=pd.Timestamp(scope['ex_date'],tz='America/New_York')+pd.Timedelta(hours=9,minutes=30);accepted=pd.Timestamp(proof['accepted_at_utc']);_require(accepted.tzinfo is not None and accepted<ex and ex<pd.Timestamp('2026-01-01',tz='America/New_York'),'R14_ORIGINAL_CURRENT_UNIT_PREEX_REQUIRED');parts=proof['source_body_parts'];doc=pinned(proof['source_document_ref'])

    def piece(name):

        p=parts[name];a,b=p['byte_range'];_require(0<=a<b<=doc.stat().st_size and b-a<=8192,'R14_BOUNDED_CURRENT_SUBJECT_FRAGMENT_REQUIRED')

        with doc.open('rb') as f:f.seek(a);raw=f.read(b-a)

        _require(raw==pinned(p['original_fragment_ref']).read_bytes() and raw.decode()==p['literal'],'R14_CURRENT_SUBJECT_PHYSICAL_BYTES_REQUIRED');return raw

    current=piece('current_statement');context=piece('current_common_context');unit=piece('USD_per_share_unit')

    unit_proof=dict(accepted_header_ref=proof['accepted_header_ref'],accepted_at_utc=proof['accepted_at_utc'],source_form=proof['source_form'],accession=proof['accession'],source_document_ref=proof['source_document_ref'],capital_fragment_byte_range=parts['current_statement']['byte_range'],capital_fragment_ref=parts['current_statement']['original_fragment_ref'],original_capital_row_literal=parts['current_statement']['visible_literal'],USD_per_common_share_unit_metadata=[dict(id='usdPerShare',byte_start=parts['USD_per_share_unit']['byte_range'][0],byte_end=parts['USD_per_share_unit']['byte_range'][1],original_unit_markup=unit.decode())])

    _original_common_cash_usd_unit(unit_proof,pinned,issuer_cik=1156039,concept='us-gaap:CommonStockDividendsPerShareDeclared',class_literal='our Audit Committee declared a fourth quarter 2025 dividend to shareholders of')

    tag=re.findall(rb'<ix:nonFraction\b[^>]*name="us-gaap:CommonStockDividendsPerShareDeclared"[^>]*>.*?</ix:nonFraction>',current,re.S);_require(len(tag)==1 and all(x in tag[0] for x in (b'unitRef="usdPerShare"',b'contextRef="c-276"',b'scale="0"',b'>1.71</ix:nonFraction>')),'R14_ONE_EXACT_CURRENT_COMMON_DECLARED_RAW_USD_AMOUNT_TAG_REQUIRED')

    import xml.etree.ElementTree as ET

    root=ET.fromstring(b'<root xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">'+context+b'</root>')[0];ns={'x':'http://www.xbrl.org/2003/instance','d':'http://xbrl.org/2006/xbrldi'};identifier=root.find('x:entity/x:identifier',ns);members=root.findall('x:entity/x:segment/d:explicitMember',ns);period=root.find('x:period',ns)

    _require(root.attrib=={'id':'c-276'} and identifier is not None and identifier.attrib.get('scheme')=='http://www.sec.gov/CIK' and identifier.text=='0001156039' and len(members)==1 and members[0].attrib=={'dimension':'us-gaap:SubsequentEventTypeAxis'} and members[0].text=='us-gaap:SubsequentEventMember' and period is not None and [x.tag.rsplit('}',1)[-1] for x in period]==['startDate','endDate'] and [x.text for x in period]==['2025-10-15','2025-10-15'],'R14_EXACT_CURRENT_DECLARATION_CIK_CONTEXT_AND_DATE_REQUIRED')

    from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(current.decode());visible=' '.join(' '.join(parser.parts).split());expected='On October 15, 2025, our Audit Committee declared a fourth quarter 2025 dividend to shareholders of $ 1.71 per share, payable on December 19, 2025 to shareholders of record at the close of business on December 5, 2025.'

    _require(visible==expected==parts['current_statement']['visible_literal'] and hashlib.sha256(visible.encode()).hexdigest()==parts['current_statement']['visible_literal_sha256'],'R14_EXACT_CURRENT_COMMON_DECLARATION_AND_RECORD_PAY_REQUIRED')

    base=_base();frozen=base._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer']);_require(frozen is not None,'R14_EXACT_ORIGINAL_FROZEN_ELV_IDENTITY_REQUIRED');row=frozen['original_source_row'];raw=base._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned)

    _require(row['title_of_class']=='COM' and row['ticker']=='ELV' and row['cusip']==row['security_id']=='036752103' and raw['security_uid']=='CUSIP:036752103' and raw['accounting_sid']==scope['accounting_sid'] and raw['prior_date']==scope['prior_date'] and raw['ex_date']==scope['ex_date'] and raw['same_dated_UID_and_SID'] is True and raw['share_quantity_effect'] is False,'R14_CURRENT_COMMON_CLASS_AND_ORIGINAL_DATED_CUSIP_REQUIRED')

    return _VerifiedClass(profile=ELV_CURRENT_COMMON,current_subject_proof_ref=scope['current_subject_proof_ref'],source_common_class_literal='Common Stock',original_frozen_class_literal='COM',original_CUSIP='036752103',ticker='ELV',row_unchanged=True,current_statement_and_common_declared_XBRL_subject_bound=True,source_USD_per_raw_share_unit_bound=True,share_quantity_effect=False)



def _bac_percent_statement_semantics(text,facts,publication,*,listed_common_class=None):

    scope=BAC_PERCENT_SCOPE

    _require(listed_common_class is None and text==scope['original_current_literal'] and facts.get('ticker')==scope['ticker'] and facts.get('sec_filer_cik')==scope['issuer_CIK'] and facts.get('security_id')==scope['accounting_sid'] and facts.get('exact_frozen_event_key',{}).get('effective_date')==scope['ex_date'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal('0.24') and pd.Timestamp(publication)==pd.Timestamp('2023-07-31'),'R16_EXACT_ORIGINAL_BAC_CURRENT_LITERAL_EVENT_AND_CLOCK_REQUIRED')

    _require(re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==['0.24'] and text.count('nine percent')==1 and text.count('percent')==1 and 'declared a quarterly common stock dividend of $0.24 per share' in text,'R16_ONE_CURRENT_AND_ONE_NONMONETARY_PERCENT_ROLE_REQUIRED')

    return dict(profile=BAC_CURRENT_PERCENT,amount_roles=[dict(role='EXPLICIT_ORIGINAL_CURRENT_COMMON_QUARTER_CASH',literal='0.24'),dict(role='NONMONETARY_PRIOR_COMPARISON_CONTEXT',original_percent_literal='nine percent',is_cash_amount=False,old_cash_amount_supplied_by_source=False)],selected_current_amount='0.24',record_date=facts['record_date'],pay_date=facts['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['source_role_proof_ref']),cash_payment_basis='USD_PER_RAW_OLD_SHARE_AFTER_NATIVE_US_CHARTER_AND_EXACT_RAW_GATES',old_amounts_not_discarded=True,original_text_not_rewritten=True,annual_rate_divided_or_inferred=False,prior_cash_amount_inferred_from_percent=False,current_cash_computed_from_percent_or_prior=False)



def _bac_percent_original_support(payload,entry,facts,pinned):

    scope=BAC_PERCENT_SCOPE;base=_base()

    _require(payload.get('bac_exact_current_nonmonetary_percent_scope')==scope and payload.get('sec_source_transport_profile')==base.SEC_STATIC_PRIMARY_BODY_PROFILE and payload.get('sec_cash_statement_profile')==BAC_CURRENT_PERCENT,'R16_EXACT_STATIC_PRIMARY_BAC_OPT_IN_REQUIRED')

    _require(facts.get('listing_identity')=='NYSE:BAC' and facts.get('currency')=='USD' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and facts.get('available_at') is None and entry['prior_raw_close']['prior_date']==scope['prior_date'],'R16_UNCHANGED_ORIGINAL_USD_RAW_COMMON_UNIT_REQUIRED')

    proof=json.loads(pinned(scope['source_role_proof_ref']).read_text(encoding='utf-8'));event=proof['event'];selected=proof['selected_original_current_fragment']

    _require(proof['schema']=='BAC_EXACT_2023_08_31_CURRENT_ONE_CASH_NONMONETARY_PERCENT_SOURCE_ROLE_PROOF_R16_R1' and event=={k:scope[k] for k in ('ticker','ex_date','prior_date','issuer_CIK','original_CUSIP','accounting_sid','record_date','pay_date','publication_accepted_at_utc','declaration_date')} and proof['original_current_literal']==scope['original_current_literal'] and proof['original_money_tokens']==['0.24'] and proof['first_publication_at'] is None and proof['engine_available_at'] is None,'R16_PINNED_ORIGINAL_CURRENT_ROLE_PROOF_REQUIRED')

    _bac_percent_statement_semantics(selected['text'],facts,'2023-07-31')

    same=lambda a,b:all(a[k]==b[k] for k in ('path','sha256'))

    _require(payload['selected_original_cash_fragment']==selected and same(payload['sec_cash_source_custody_ref'],proof['source_custody_ref']) and same(payload['same_file_cash_identity_support_ref'],proof['common_cover_support_ref']) and same(payload['frozen_account_identity_ref'],proof['original_frozen_identity_ref']),'R16_EXACT_ORIGINAL_FRAGMENT_SOURCE_AND_COM_CUSTODY_REQUIRED')

    source=json.loads(pinned(payload['sec_cash_source_custody_ref']).read_text(encoding='utf-8'));_require(same(source['original_HTTP_ref'],proof['original_same_full_submission_ref']),'R16_SAME_ORIGINAL_FULL_SUBMISSION_REQUIRED')

    doc=pinned(_path_sha_ref(proof['original_same_full_submission_ref']));a,b=selected['original_byte_range'];parent=proof['primary_member']['text_byte_range'];_require(type(a) is int and type(b) is int and parent[0]<=a<b<=parent[1]<=doc.stat().st_size and b-a==466,'R16_FULL_ORIGINAL_466_BYTE_CURRENT_FRAGMENT_REQUIRED')

    with doc.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)

    _require(raw==pinned(selected['original_fragment_ref']).read_bytes(),'R16_ORIGINAL_CURRENT_PHYSICAL_BYTES_REQUIRED')

    from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(raw.decode('utf-8'));_require(' '.join(' '.join(parser.parts).split())==scope['original_current_literal'] and pinned(selected['text_projection_ref']).read_text(encoding='utf-8-sig').rstrip('\n')==scope['original_current_literal'],'R16_NATIVE_ORIGINAL_TEXT_PROJECTION_REQUIRED')

    frozen=base._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer']);_require(frozen is not None,'R16_ORIGINAL_FROZEN_COM_REQUIRED');row=frozen['original_source_row'];dated=base._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned)

    _require(row['title_of_class']=='COM' and row['ticker']=='BAC' and row['cusip']==row['security_id']==scope['original_CUSIP'] and dated['security_uid']=='CUSIP:'+scope['original_CUSIP'] and dated['accounting_sid']==scope['accounting_sid'] and dated['prior_date']==scope['prior_date'] and dated['ex_date']==scope['ex_date'] and dated['same_dated_UID_and_SID'] is True and dated['share_quantity_effect'] is False,'R16_EXACT_ORIGINAL_COM_CUSIP_AND_DATED_RAW_UID_REQUIRED')

    return None



def _qcom_policy_statement_semantics(text,facts,publication,*,listed_common_class=None):

    scope=QCOM_POLICY_SCOPE

    _require(listed_common_class is None and text==scope['original_current_literal'] and facts.get('ticker')==scope['ticker'] and facts.get('sec_filer_cik')==scope['issuer_CIK'] and facts.get('security_id')==scope['accounting_sid'] and facts.get('exact_frozen_event_key',{}).get('ticker')=='QCOM' and facts['exact_frozen_event_key'].get('effective_date')==scope['ex_date'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal('0.85') and pd.Timestamp(publication)==pd.Timestamp('2024-05-01'),'R17_EXACT_ORIGINAL_QCOM_CURRENT_EVENT_LITERAL_AND_CLOCK_REQUIRED')

    _require(re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==['0.80','0.85','0.85'] and 'quarterly dividend per share of common stock' in text and 'effective for dividends payable after March 21, 2024' in text and 'we announced a cash dividend of $ 0.85 per share on our common stock' in text and pd.Timestamp(scope['quarterly_policy_effective_after_date'])<pd.Timestamp(facts['pay_date']),'R17_ORIGINAL_CURRENT_ANNOUNCEMENT_AND_QUARTER_POLICY_DATE_RELATION_REQUIRED')

    return dict(profile=QCOM_CURRENT_POLICY,amount_roles=[dict(role='PRIOR_QUARTERLY_POLICY_COMPARISON_NOT_CURRENT_CASH',literal='0.80'),dict(role='ANNOUNCED_NEW_QUARTERLY_POLICY_RATE_NOT_CURRENT_PAYMENT',literal='0.85'),dict(role='EXPLICIT_CURRENT_ANNOUNCED_COMMON_CASH',literal='0.85')],selected_current_amount='0.85',record_date=facts['record_date'],pay_date=facts['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['source_role_proof_ref']),cash_payment_basis='USD_PER_RAW_OLD_SHARE_AFTER_NATIVE_US_CHARTER_AND_EXACT_RAW_GATES',old_amounts_not_discarded=True,original_text_not_rewritten=True,announced_not_rewritten_as_declared=True,current_amount_inferred_from_policy=False,quarterly_policy_and_current_cash_amount_concordant=True,annual_amount_created=False,annual_rate_divided_or_inferred=False,current_amount_from_reported_concept=False)



def _qcom_original_policy_support(payload,entry,facts,pinned):

    scope=QCOM_POLICY_SCOPE;base=_base()

    _require(payload.get('qcom_exact_current_announcement_quarter_policy_scope')==scope and payload.get('sec_cash_statement_profile')==QCOM_CURRENT_POLICY and payload.get('sec_source_transport_profile')==base.SEC_STATIC_PRIMARY_BODY_PROFILE,'R17_EXACT_QCOM_STATIC_PRIMARY_OPT_IN_REQUIRED')

    _require(facts.get('listing_identity')=='NASDAQ:QCOM' and facts.get('currency')=='USD' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and facts.get('available_at') is None and entry['prior_raw_close']['prior_date']==scope['prior_date'],'R17_UNCHANGED_ORIGINAL_USD_RAW_COMMON_UNIT_REQUIRED')

    proof=json.loads(pinned(scope['source_role_proof_ref']).read_text(encoding='utf-8'));event=proof['event'];_require(proof['schema']=='QCOM_EXACT_2024_05_30_ORIGINAL_CURRENT_ANNOUNCED_COMMON_CASH_BOUND_QUARTER_POLICY_SOURCE_ROLE_PROOF_R17_R1' and event=={k:scope[k] for k in ('ticker','ex_date','prior_date','issuer_CIK','original_CUSIP','accounting_sid','record_date','pay_date','policy_announcement_date','quarterly_policy_effective_after_date','current_cash_announcement_date','publication_accepted_at_utc')} and proof['current_native_FilingText_space_join_literal']==scope['original_current_literal'] and proof['original_money_tokens']==['0.80','0.85','0.85'] and proof['first_publication_at'] is None and proof['engine_available_at'] is None,'R17_PINNED_ORIGINAL_QCOM_POLICY_CURRENT_PROOF_REQUIRED')

    _qcom_policy_statement_semantics(payload['selected_original_cash_fragment']['text'],facts,'2024-05-01')

    same=lambda a,b:_path_sha_ref(a)==_path_sha_ref(b);source=json.loads(pinned(payload['sec_cash_source_custody_ref']).read_text(encoding='utf-8'));selected=payload['selected_original_cash_fragment'];_require(same(source['original_HTTP_ref'],proof['source_original_full_submission_ref']) and same(selected['original_fragment_ref'],proof['original_current_fragment_ref']) and selected['original_byte_range']==proof['selected_original_current_full_byte_range'],'R17_EXACT_ORIGINAL_FULL_AND_CURRENT_FRAGMENT_REQUIRED')

    doc=pinned(_path_sha_ref(proof['source_original_full_submission_ref']));parent=proof['original_primary_member']['text_byte_range'];pieces={}

    for name in ('ORIGINAL_CURRENT_CASH_DECLARATION_PARAGRAPH','ORIGINAL_XBRL_USD_PER_SHARE_UNIT_CONTEXT'):

        matches=[z for z in proof['physical_bounded_bindings'] if z['fragment_role']==name];_require(len(matches)==1,'R17_ONE_ORIGINAL_CURRENT_AND_UNIT_FRAGMENT_REQUIRED');z=matches[0];a,b=z['full_byte_range'];_require(type(a) is int and type(b) is int and parent[0]<=a<b<=parent[1]<=doc.stat().st_size and b-a==({'ORIGINAL_CURRENT_CASH_DECLARATION_PARAGRAPH':1676,'ORIGINAL_XBRL_USD_PER_SHARE_UNIT_CONTEXT':246}[name]),'R17_EXACT_BOUNDED_ORIGINAL_CURRENT_UNIT_BYTES_REQUIRED')

        with doc.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)

        _require(raw==pinned(_path_sha_ref(z['original_fragment_ref'])).read_bytes(),'R17_SAME_FULL_ORIGINAL_PHYSICAL_BYTES_REQUIRED');pieces[name]=raw

    from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(pieces['ORIGINAL_CURRENT_CASH_DECLARATION_PARAGRAPH'].decode('utf-8'));_require(' '.join(' '.join(parser.parts).split())==scope['original_current_literal'],'R17_ORIGINAL_NATIVE_FILINGTEXT_PROJECTION_REQUIRED');unit=pieces['ORIGINAL_XBRL_USD_PER_SHARE_UNIT_CONTEXT'];_require(re.search(rb'<xbrli:unitNumerator>\s*<xbrli:measure>iso4217:USD</xbrli:measure>\s*</xbrli:unitNumerator>',unit) and re.search(rb'<xbrli:unitDenominator>\s*<xbrli:measure>xbrli:shares</xbrli:measure>\s*</xbrli:unitDenominator>',unit),'R17_ORIGINAL_USD_PER_SHARE_UNIT_REQUIRED')

    frozen=base._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer']);_require(frozen is not None,'R17_ORIGINAL_FROZEN_COM_REQUIRED');row=frozen['original_source_row'];dated=base._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned)

    _require(row['title_of_class']=='COM' and row['ticker']=='QCOM' and row['cusip']==row['security_id']==scope['original_CUSIP'] and dated['security_uid']=='CUSIP:'+scope['original_CUSIP'] and dated['accounting_sid']==scope['accounting_sid'] and dated['prior_date']==scope['prior_date'] and dated['ex_date']==scope['ex_date'] and dated['same_dated_UID_and_SID'] is True and dated['share_quantity_effect'] is False,'R17_EXACT_ORIGINAL_COM_CUSIP_AND_DATED_RAW_UID_REQUIRED')

    return None



def _r18_static_statement_semantics(profile,text,facts,publication,*,listed_common_class=None):

    scope=PRMB_CURRENT_SCOPE if profile==PRMB_CURRENT_CLASS_A else KBR_CURRENT_SCOPE

    _require(profile in (PRMB_CURRENT_CLASS_A,KBR_CURRENT_COMMON) and text==scope['original_current_literal'] and facts.get('ticker')==scope['ticker'] and facts.get('sec_filer_cik')==scope['issuer_CIK'] and facts.get('security_id')==scope['accounting_sid'] and facts.get('exact_frozen_event_key',{}).get('ticker')==scope['ticker'] and facts['exact_frozen_event_key'].get('effective_date')==scope['ex_date'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal(scope['current_amount_literal']) and pd.Timestamp(publication)==pd.Timestamp(scope['publication_date']) and listed_common_class==('A' if profile==PRMB_CURRENT_CLASS_A else None),'R18_EXACT_ORIGINAL_STATIC_EVENT_LITERAL_CLASS_AND_CLOCK_REQUIRED')

    expected=['0.10'] if profile==PRMB_CURRENT_CLASS_A else ['0.135','0.15'];_require(re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==expected,'R18_ALL_ORIGINAL_STATIC_AMOUNT_ROLES_REQUIRED')

    roles=[dict(role='EXPLICIT_CURRENT_COMMON_CASH_FROM_ORIGINAL_QUARTER_PRESS',literal='0.10')] if profile==PRMB_CURRENT_CLASS_A else [dict(role='PRIOR_QUARTER_REGULAR_COMPARISON_NOT_CURRENT_CASH',literal='0.135'),dict(role='EXPLICIT_APPROVED_CURRENT_REGULAR_QUARTER_CASH',literal='0.15'),dict(role='NONMONETARY_PRIOR_COMPARISON_CONTEXT',original_percent_literal='11%',is_cash_amount=False)]

    return dict(profile=profile,amount_roles=roles,selected_current_amount=scope['current_amount_literal'],record_date=facts['record_date'],pay_date=facts['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['proof_ref']),cash_payment_basis='USD_PER_RAW_OLD_SHARE_AFTER_ORIGINAL_NATIVE_US_CHARTER_AND_EXACT_RAW_GATES',old_amounts_not_discarded=True,original_text_not_rewritten=True,annual_rate_divided_or_inferred=False,current_computed_from_prior_or_percentage=False,independent_current_common_subject_proved=True,board_declaration_date=scope['board_declaration_date'],board_date_not_publication_date=True)



def _r18_static_current_support(payload,entry,facts,listing,pinned):

    profile=payload['sec_cash_statement_profile'];scope=PRMB_CURRENT_SCOPE if profile==PRMB_CURRENT_CLASS_A else KBR_CURRENT_SCOPE;key='prmb_exact_current_ClassA_scope' if profile==PRMB_CURRENT_CLASS_A else 'kbr_exact_current_common_scope'

    _require(payload.get(key)==scope and payload.get('sec_source_transport_profile')==_base().SEC_STATIC_SUBMISSION_PROFILE and facts.get('listing_identity')=='NYSE:'+scope['ticker'] and facts.get('currency')=='USD' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and facts.get('available_at') is None and entry['prior_raw_close']['prior_date']==scope['prior_date'],'R18_EXACT_STATIC_CURRENT_SCOPE_AND_UNCHANGED_RAW_UNIT_REQUIRED')

    selected=payload['selected_original_cash_fragment'];_require(selected['text']==scope['original_current_literal'] and selected['original_fragment_ref']['sha256']==scope['original_fragment_sha256'],'R18_EXACT_ORIGINAL_MAIN_CURRENT_FRAGMENT_REQUIRED');_r18_static_statement_semantics(profile,selected['text'],facts,scope['publication_date'],listed_common_class='A' if profile==PRMB_CURRENT_CLASS_A else None)

    proof=json.loads(pinned(scope['proof_ref']).read_text(encoding='utf-8'));identity=proof['original_frozen_dated_identity'];row=identity['original_frozen_row'];dated=identity['event'];_require(row['ticker']==scope['ticker'] and row['cusip']==row['security_id']==scope['original_CUSIP'] and row['title_of_class']==('CLASS A COM SHS' if profile==PRMB_CURRENT_CLASS_A else 'COM') and dated['prior_date']==scope['prior_date'] and dated['effective_date']==scope['ex_date'] and dated['same_dated_cusip_and_accounting_sid'] is True and dated['ex_identity']==dated['prior_identity']==dict(security_uid='CUSIP:'+scope['original_CUSIP'],accounting_sid=scope['accounting_sid']),'R18_ORIGINAL_DATED_CLASS_TITLE_CUSIP_AND_UID_REQUIRED')

    frozen=json.loads(pinned(payload['frozen_account_identity_ref']).read_text(encoding='utf-8-sig'));rows=[x['original_source_row'] for x in frozen['rows'] if x['original_source_row']['ticker']==scope['ticker']];_require(len(rows)==1 and all((pd.Timestamp(rows[0][k])==pd.Timestamp(v) if k in ('effective_start','effective_end') else rows[0][k]==v) for k,v in row.items()),'R18_UNCHANGED_COMPLETE_FROZEN_CLASS_ROW_REQUIRED')

    if profile==PRMB_CURRENT_CLASS_A:

        _require(proof['event']=={k:scope[k] for k in ('ticker','ex_date','prior_date','issuer_CIK','original_CUSIP','original_frozen_class_literal','accounting_sid','record_date','pay_date','board_declaration_date','press_publication_date','current_amount_literal')} and proof['current_class_dimension']=='us-gaap:CommonClassAMember' and proof['current_context_period']=='2025-11-05','R18_CURRENT_PRMB_CLASSA_SOURCE_EVENT_REQUIRED');parts=proof['current_source_body_parts'];doc=pinned(_path_sha_ref(proof['source_document_ref']))

        for name in ('current_tagged_statement','current_ClassA_context','USD_per_share_unit'):

            part=parts[name];a,b=part['byte_range'];_require(0<=a<b<=doc.stat().st_size and b-a<=8192,'R18_BOUNDED_ORIGINAL_CURRENT_CLASSA_BYTES_REQUIRED')

            with doc.open('rb') as f:f.seek(a);raw=f.read(b-a)

            _require(raw==pinned(_path_sha_ref(part['original_fragment_ref'])).read_bytes(),'R18_CURRENT_CLASSA_PHYSICAL_BYTES_REQUIRED')

        _original_common_cash_usd_unit(proof['original_shared_unit_input'],pinned,issuer_cik=2042694,concept='us-gaap:CommonStockDividendsPerShareDeclared',class_literal='outstanding Class A common stock');context=pinned(_path_sha_ref(parts['current_ClassA_context']['original_fragment_ref'])).read_bytes();tagged=pinned(_path_sha_ref(parts['current_tagged_statement']['original_fragment_ref'])).read_bytes()

        _require(all(x in context for x in (b'id="c-360"',b'>0002042694</xbrli:identifier>',b'dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassAMember',b'dimension="us-gaap:SubsequentEventTypeAxis">us-gaap:SubsequentEventMember',b'<xbrli:startDate>2025-11-05</xbrli:startDate>',b'<xbrli:endDate>2025-11-05</xbrli:endDate>')) and all(x in tagged for x in (b'contextRef="c-360"',b'unitRef="usdPerShare"',b'name="us-gaap:CommonStockDividendsPerShareDeclared"',b'scale="0"',b'>0.10</ix:nonFraction>')),'R18_EXACT_CURRENT_PRMB_CLASSA_CONTEXT_AND_AMOUNT_REQUIRED')

        return _VerifiedClass(profile=profile,source_common_class_literal='Class A Common Stock',original_frozen_class_literal='CLASS A COM SHS',original_CUSIP=scope['original_CUSIP'],ticker='PRMB',row_unchanged=True,source_current_ClassA_context_bound=True,no_class_alias=True)

    note=proof['current_common_primary_source'];doc=pinned(_path_sha_ref(note['source_original_primary_ref']));a,b=note['original_current_paragraph_byte_range'];_require(0<=a<b<=doc.stat().st_size and b-a==742,'R18_EXACT_KBR_COMMON_CURRENT_PARAGRAPH_REQUIRED')

    with doc.open('rb') as f:f.seek(a);raw=f.read(b-a)

    _require(raw==pinned(_path_sha_ref(note['original_current_paragraph_ref'])).read_bytes(),'R18_KBR_CURRENT_COMMON_PHYSICAL_BYTES_REQUIRED');from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(raw.decode());text=' '.join(' '.join(parser.parts).split());_require(text==note['original_paragraph_complete_literal'] and 'Our common stock is listed on the NYSE' in text and 'quarterly cash dividends' in text and 'On February 19, 2024' in text and 'April 15, 2024' in text and re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==['0.15'] and proof['record_Mar15_from_original_main_EX99_only'] is True,'R18_KBR_SAME_CURRENT_COMMON_QUARTER_CASH_PAY_AND_RECORD_BINDING_REQUIRED')

    header=pinned(_path_sha_ref(note['actual_HEADER_ref'])).read_bytes();_require(b'0001357615-24-000016' in header and re.search(rb'CENTRAL INDEX KEY:\s*0*1357615\b',header) and b'<ACCEPTANCE-DATETIME>20240220121123' in header and pd.Timestamp(note['actual_HEADER_accepted_at_utc'])<pd.Timestamp(scope['ex_date'],tz='America/New_York'),'R18_KBR_REAL_PREEX_CURRENT_COMMON_HEADER_REQUIRED');return None



def _apo_first_quarter_semantics(text,facts,publication):

    scope=APO_FIRST_QUARTER_SCOPE

    _require(text==scope['original_current_literal'] and facts.get('ticker')=='APO' and facts.get('sec_filer_cik')==1858681 and facts.get('security_id')==scope['accounting_sid'] and facts.get('exact_frozen_event_key',{}).get('ticker')=='APO' and facts['exact_frozen_event_key'].get('effective_date')==scope['ex_date'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal('0.4625') and pd.Timestamp(publication)==pd.Timestamp(scope['source_publication_date']),'R19_EXACT_APO_CURRENT_COMMON_FIRST_QUARTER_LITERAL_AND_EVENT_REQUIRED')

    _require(re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==['0.4625'] and 'per share of its Common Stock for the first quarter ended March 31, 2024' in text,'R19_ORIGINAL_SINGLE_CURRENT_COMMON_QUARTER_CASH_REQUIRED')

    return dict(profile=scope['profile'],amount_roles=[dict(role='EXPLICIT_CURRENT_COMMON_CASH_FOR_ORIGINAL_NAMED_FIRST_QUARTER',literal='0.4625')],selected_current_amount='0.4625',record_date=facts['record_date'],pay_date=facts['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['source_role_proof_ref']),original_quarter_phrase='for the first quarter ended March 31, 2024',quarter_period_end_not_publication_date=True,old_amounts_not_discarded=True,original_text_not_rewritten=True,annual_rate_divided_or_inferred=False,current_computed_from_other_quarters_or_preferred=False,current_amount_from_reported_capital=False)



def _apo_exact_capture_equivalence(proof,pinned):

    receipt=json.loads(pinned(_path_sha_ref(proof['exact_old_new_transport_equivalence_receipt_ref'])).read_text(encoding='utf-8'))

    _require(receipt['schema']=='APO_ONE_FINAL_MAIN_NEW_ACTUAL_HTTP_CAPTURE_R1' and receipt['old_UNKNOWN_status_and_original_source_files_untouched'] is True and receipt['new200_is_current_transport_observation_not_source_publication_clock'] is True and len(receipt['events'])==1,'R19_EXACT_APO_NAMED_TRANSPORT_EQUIVALENCE_REQUIRED')

    e=receipt['events'][0];pins=e['original_pins'];a=e['attempts'];old=proof['original_main_full_ref'];new=proof['new_actual_main_full_ref']

    _require(e['ticker']=='APO' and e['effective_date']=='2024-05-16' and pins['CIK']==1858681 and pins['accession']=='0001858681-24-000044' and _path_sha_ref(e['old_full_ref'])==_path_sha_ref(old) and _path_sha_ref(e['successful_new_full_ref'])==_path_sha_ref(new) and _path_sha_ref(e['old_HEADER_ref'])==_path_sha_ref(proof['original_main_HEADER_ref']) and old['sha256']==new['sha256']==pins['old_full_SHA'] and old['bytes']==new['bytes']==pins['old_full_bytes'] and len(a)==1,'R19_EXACT_APO_OLD_AND_NEW_PHYSICAL_CAPSULE_PAIR_REQUIRED')

    a=a[0];_require(a['response_status']==200 and a['actual_HTTP_status_observed'] is True and a['old_HTTP_status_remains_UNKNOWN'] is True and a['new_full_matches_old_SHA_size_and_bytewise'] is True and a['new_HEADER_prefix_matches_old_exactly'] is True and a['new_SEC_HEADER_matches_old_exactly'] is True and pd.Timestamp(e['source_accepted_at_utc'])==pd.Timestamp(APO_FIRST_QUARTER_SCOPE['publication_accepted_at_utc']),'R19_ACTUAL_APO_CAPTURE_BYTE_AND_HEADER_EQUIVALENCE_REQUIRED')

    pinned(_path_sha_ref(old));pinned(_path_sha_ref(new));return _path_sha_ref(new)



def _apo_first_quarter_support(payload,entry,facts,pinned):

    scope=APO_FIRST_QUARTER_SCOPE

    _require(payload.get('apo_exact_current_first_quarter_scope')==scope and payload.get('sec_source_transport_profile')==_base().SEC_STATIC_SUBMISSION_PROFILE and facts.get('listing_identity')=='NYSE:APO' and facts.get('currency')=='USD' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and facts.get('available_at') is None and entry['prior_raw_close']['prior_date']==scope['prior_date'],'R19_EXACT_APO_UNCHANGED_CURRENCY_RAW_UNIT_AND_PRIOR_REQUIRED')

    selected=payload['selected_original_cash_fragment'];_apo_first_quarter_semantics(selected['text'],facts,scope['source_publication_date']);_require(selected['original_fragment_ref']['sha256']==scope['original_current_fragment_sha256'],'R19_EXACT_CURRENT_APO_ORIGINAL_FRAGMENT_REQUIRED')

    proof=json.loads(pinned(scope['source_role_proof_ref']).read_text(encoding='utf-8'));event={k:scope[k] for k in ('ticker','ex_date','prior_date','issuer_CIK','original_CUSIP','accounting_sid','record_date','pay_date','source_publication_date','publication_accepted_at_utc','quarter_ended_date','current_amount_literal')}

    _require(proof['event']==event and proof['current_native_original_literal']==selected['text'] and proof['original_current_money_tokens']==['0.4625'] and proof['actual_first_publication_at'] is None and proof['engine_available_at'] is None and proof['financial_values_not_current_amount_or_class_override'] is True,'R19_PINNED_APO_CURRENT_ROLE_AND_UNKNOWN_AVAILABILITY_REQUIRED')

    _apo_exact_capture_equivalence(proof,pinned)

    doc=pinned(_path_sha_ref(proof['original_main_cash_document_ref']));a,b=proof['original_current_document_byte_range'];_require(b-a==449 and 0<=a<b<=doc.stat().st_size,'R19_ORIGINAL_APO_449B_CURRENT_SCOPE_REQUIRED')

    with doc.open('rb') as f:f.seek(a);raw=f.read(b-a)

    _require(raw==pinned(_path_sha_ref(proof['original_current_fragment_ref'])).read_bytes(),'R19_ORIGINAL_APO_CURRENT_PHYSICAL_BYTES_REQUIRED')

    frozen=_base()._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer']);_require(frozen is not None,'R19_ORIGINAL_APO_FROZEN_COM_REQUIRED');row=frozen['original_source_row'];dated=_base()._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned)

    _require(row['ticker']=='APO' and row['title_of_class']=='COM' and row['cusip']==row['security_id']=='03769M106' and dated['prior_date']==scope['prior_date'] and dated['ex_date']==scope['ex_date'] and dated['same_dated_UID_and_SID'] is True and dated['security_uid']=='CUSIP:03769M106' and dated['accounting_sid']==scope['accounting_sid'],'R19_EXACT_APO_ORIGINAL_COM_CUSIP_AND_DATED_UID_REQUIRED')

    return None



def _qcom_context_scope(facts):

    ex=facts.get('exact_frozen_event_key',{}).get('effective_date');scope=QCOM_CONTEXT_SCOPES.get(ex)

    _require(scope is not None and facts.get('ticker')=='QCOM' and facts.get('sec_filer_cik')==804328 and facts.get('security_id')==scope['accounting_sid'] and facts['exact_frozen_event_key'].get('ticker')=='QCOM','R20_EXACT_TWO_QCOM_EVENT_TUPLES_REQUIRED')

    return scope



def _qcom_context_semantics(text,facts,publication,*,listed_common_class=None):

    scope=_qcom_context_scope(facts)

    _require(listed_common_class is None and text==scope['original_current_literal'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal(scope['current_amount_literal']) and pd.Timestamp(publication)==pd.Timestamp(scope['source_publication_date']),'R20_EXACT_CURRENT_ANNOUNCED_COMMON_LITERAL_AMOUNT_DATES_REQUIRED')

    _require(re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==scope['original_money_tokens'],'R20_ALL_ORIGINAL_CURRENT_POLICY_MONEY_ROLES_REQUIRED')

    roles=[dict(role='EXPLICIT_CURRENT_ANNOUNCED_COMMON_CASH',literal=scope['current_amount_literal'])]

    if scope['ex_date']=='2025-06-05':

        _require('quarterly dividend per share of common stock from $ 0.85 to $ 0.89' in text and 'effective for dividends payable after March 27, 2025' in text and pd.Timestamp('2025-03-27')<pd.Timestamp(scope['pay_date']),'R20_ORIGINAL_POLICY_EFFECTIVE_DATE_CURRENT_PAY_REQUIRED')

        roles=[dict(role='PRIOR_QUARTERLY_POLICY_COMPARISON_NOT_CURRENT_CASH',literal='0.85'),dict(role='ANNOUNCED_NEW_QUARTERLY_POLICY_RATE_NOT_CURRENT_PAYMENT',literal='0.89'),*roles]

    return dict(profile=QCOM_CURRENT_CONTEXT,amount_roles=roles,selected_current_amount=scope['current_amount_literal'],record_date=scope['record_date'],pay_date=scope['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['source_role_proof_ref']),quarter_authority='ORIGINAL_CURRENT_COMMON_DECLARED_SUBSEQUENT_EVENT_DIVIDENDS_QUARTER_MEMBER',original_quarter_member=scope['quarter_member'],announced_not_rewritten_as_declared=True,original_text_not_rewritten=True,old_amounts_not_discarded=True,current_amount_from_reported_concept=False,current_amount_inferred_from_policy=False,annual_amount_created=False,annual_rate_divided_or_inferred=False)



def _qcom_current_context_support(payload,entry,facts,pinned):

    scope=_qcom_context_scope(facts);base=_base();same=lambda a,b:_path_sha_ref(a)==_path_sha_ref(b)

    _require(payload.get('qcom_exact_current_quarter_context_scope')==scope and payload.get('sec_source_transport_profile')==base.SEC_STATIC_PRIMARY_BODY_PROFILE and facts.get('listing_identity')=='NASDAQ:QCOM' and facts.get('currency')=='USD' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and facts.get('available_at') is None and entry['prior_raw_close']['prior_date']==scope['prior_date'],'R20_EXACT_SCOPE_ORIGINAL_USD_RAW_COMMON_UNIT_REQUIRED')

    proof=json.loads(pinned(scope['source_role_proof_ref']).read_text(encoding='utf-8'));_require(proof['schema']=='QCOM_TWO_EXACT_CURRENT_COMMON_QUARTER_CONTEXT_SOURCE_ROLE_PROOF_R20_R1' and proof['event']=={k:v for k,v in scope.items() if k!='source_role_proof_ref'} and proof['actual_first_publication_at'] is None and proof['engine_available_at'] is None and proof['reported_capital_values_used'] is False,'R20_PINNED_CURRENT_QUARTER_CONTEXT_PROOF_REQUIRED')

    selected=payload['selected_original_cash_fragment'];_qcom_context_semantics(selected['text'],facts,scope['source_publication_date']);source=json.loads(pinned(payload['sec_cash_source_custody_ref']).read_text(encoding='utf-8'));full=pinned(_path_sha_ref(proof['new_actual_main_full_ref']));_require(same(source['original_HTTP_ref'],proof['new_actual_main_full_ref']) and same(selected['original_fragment_ref'],proof['current_original_fragment_ref']),'R20_EXACT_CURRENT_SOURCE_AND_LITERAL_REF_REQUIRED')

    capture=json.loads(pinned(_path_sha_ref(proof['new_actual_capture_ref'])).read_text(encoding='utf-8'));_require(capture['response_status']==200 and capture['actual_HTTP_status_observed'] is True and capture['old_HTTP_status_remains_UNKNOWN'] is True and capture['new_HEADER_prefix_equals_old_exactly'] is True and capture['new_SEC_HEADER_equals_old_exactly'] is True and same(capture['original_HTTP_ref'],proof['new_actual_main_full_ref']) and capture['source_accepted_at_utc']==scope['publication_accepted_at_utc'],'R20_NEW_CURRENT_CAPTURE_ORIGINAL_HEADER_REQUIRED')

    header=pinned(_path_sha_ref(proof['actual_HEADER_ref'])).read_bytes();stamp=re.search(rb'<ACCEPTANCE-DATETIME>([0-9]{14})',header)[1].decode();accepted=pd.Timestamp(stamp).tz_localize('America/New_York').tz_convert('UTC');_require(scope['accession'].encode() in header and re.search(rb'CENTRAL INDEX KEY:\s*0*804328\b',header) and accepted==pd.Timestamp(scope['publication_accepted_at_utc']) and accepted<pd.Timestamp(scope['ex_date'],tz='America/New_York') and accepted<pd.Timestamp('2026-01-01',tz='UTC'),'R20_ACTUAL_ORIGINAL_PREEX_HEADER_CLOCK_REQUIRED')

    with full.open('rb') as stream:_require(stream.read(65536)==header,'R20_FULL_CAPTURE_OLD_HEADER_BYTE_EQUALITY_REQUIRED')

    primary=pinned(_path_sha_ref(proof['original_primary_ref']));parent=proof['original_primary_member']['text_byte_range'];pieces={};spans={}

    for role in ('original_complete_Dividends_paragraph','current_CommonStockDeclared_opening_tag','current_SubsequentEvent_context_CIK_date_XML','original_USD_divide_shares_unit_XML'):

        matches=[z for z in proof['physical_original_byte_bindings'] if z['fragment_role']==role];_require(len(matches)==1,'R20_ONE_ORIGINAL_CURRENT_CONTEXT_UNIT_FRAGMENT_REQUIRED');z=matches[0];a,b=z['new_full_submission_byte_range'];ca,cb=z['old_primary_byte_range'];_require(parent[0]<=a<b<=parent[1]<=full.stat().st_size and 0<=ca<cb<=primary.stat().st_size and b-a==cb-ca and b-a<=2048,'R20_ORIGINAL_BOUNDED_PHYSICAL_FRAGMENT_REQUIRED')

        with full.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)

        with primary.open('rb') as stream:stream.seek(ca);old=stream.read(cb-ca)

        _require(raw==old==pinned(_path_sha_ref(z['old_fragment_ref'])).read_bytes(),'R20_ORIGINAL_PRIMARY_FULL_AND_FRAGMENT_BYTES_REQUIRED');pieces[role]=raw;spans[role]=[a,b]

    cashspan=spans['original_complete_Dividends_paragraph'];_require(selected['original_byte_range']==cashspan and cashspan[0]<=spans['current_CommonStockDeclared_opening_tag'][0]<spans['current_CommonStockDeclared_opening_tag'][1]<=cashspan[1],'R20_DECLARED_CONCEPT_INSIDE_CURRENT_ANNOUNCEMENT_REQUIRED')

    from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(pieces['original_complete_Dividends_paragraph'].decode());_require(' '.join(' '.join(parser.parts).split())==scope['original_current_literal'],'R20_ORIGINAL_NATIVE_SPACE_JOIN_LITERAL_REQUIRED')

    tag=pieces['current_CommonStockDeclared_opening_tag'];context=pieces['current_SubsequentEvent_context_CIK_date_XML'];unit=pieces['original_USD_divide_shares_unit_XML']

    _require(all(x in tag for x in (b'name="us-gaap:CommonStockDividendsPerShareDeclared"',b'unitRef="usdPerShare"',('contextRef="'+scope['current_context_ref']+'"').encode(),b'scale="0"')),'R20_CURRENT_COMMON_DECLARED_CONCEPT_AND_UNIT_REQUIRED')

    _require(all(x in context for x in (('id="'+scope['current_context_ref']+'"').encode(),b'>0000804328</xbrli:identifier>',b'dimension="us-gaap:SubsequentEventTypeAxis">us-gaap:SubsequentEventMember',('dimension="us-gaap:DividendsAxis">'+scope['quarter_member']).encode(),('<xbrli:startDate>'+scope['current_announcement_date']+'</xbrli:startDate>').encode(),('<xbrli:endDate>'+scope['current_announcement_date']+'</xbrli:endDate>').encode())),'R20_SAME_CURRENT_CIK_SUBSEQUENT_EVENT_DATE_QUARTER_REQUIRED')

    _require(b'<xbrli:unit id="usdPerShare">' in unit and re.search(rb'<xbrli:unitNumerator>\s*<xbrli:measure>iso4217:USD</xbrli:measure>\s*</xbrli:unitNumerator>',unit) and re.search(rb'<xbrli:unitDenominator>\s*<xbrli:measure>xbrli:shares</xbrli:measure>\s*</xbrli:unitDenominator>',unit),'R20_ORIGINAL_USD_DIVIDE_SHARES_UNIT_REQUIRED')

    frozen=base._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer']);_require(frozen is not None,'R20_ORIGINAL_FROZEN_COM_REQUIRED');row=frozen['original_source_row'];dated=base._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned)

    _require(row['ticker']=='QCOM' and row['title_of_class']=='COM' and row['cusip']==row['security_id']=='747525103' and dated['security_uid']=='CUSIP:747525103' and dated['accounting_sid']==scope['accounting_sid'] and dated['prior_date']==scope['prior_date'] and dated['ex_date']==scope['ex_date'] and dated['same_dated_UID_and_SID'] is True and dated['share_quantity_effect'] is False,'R20_UNCHANGED_ORIGINAL_COM_CUSIP_DATED_RAW_UID_REQUIRED')

    return None



def _named_ab_scope(facts):

    key=facts.get('ticker','')+'|'+facts.get('exact_frozen_event_key',{}).get('effective_date','');scope=NAMED_AB_SCOPES.get(key)

    _require(scope is not None and facts.get('ticker')==scope['ticker'] and facts.get('sec_filer_cik')==scope['issuer_CIK'] and facts.get('security_id')==scope['accounting_sid'] and facts['exact_frozen_event_key'].get('ticker')==scope['ticker'],'R21_EXACT_TWO_NAMED_COMMON_EVENT_UID_SID_REQUIRED')

    return scope



def _named_ab_semantics(text,facts,publication,*,listed_common_class=None):

    scope=_named_ab_scope(facts)

    _require(listed_common_class=='A' and text==scope['original_current_literal'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal(scope['current_amount_literal']) and pd.Timestamp(publication)==pd.Timestamp(scope['source_publication_date']),'R21_ORIGINAL_DIRECT_CURRENT_CLASSA_CLASSB_AMOUNT_DATES_LITERAL_REQUIRED')

    _require(re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==scope['original_money_tokens'] and re.findall(r'(\d+(?:\.\d+)?)%',text)==scope['original_percent_tokens'] and {z.upper() for z in re.findall(r'\bClass\s+([A-Z])\b',text,re.I)}=={'A','B'} and 'quarterly' in text and not re.search(r'\bpreferred|depositary|ADR|ADS|converted|annualized\b',text,re.I),'R21_ALL_ORIGINAL_CURRENT_PRIOR_PERCENT_AGGREGATE_ROLES_REQUIRED')

    current=dict(role='EXPLICIT_ONE_CURRENT_QUARTER_CASH_SHARED_BY_ORIGINAL_NAMED_COMMON_A_AND_B',literal=scope['current_amount_literal'],source_common_classes=['A','B'],accounting_target_class='A')

    roles=[dict(role='PRIOR_PAID_COMMON_QUARTER_CASH_NOT_CURRENT',literal='0.75'),current,dict(role='PUBLISHED_NONMONETARY_PRIOR_COMPARISON_INCONSISTENT_NOT_USED',literal='219',unit='PERCENT')] if scope['ticker']=='FCNCA' else [current,dict(role='PUBLISHED_AGGREGATE_ESTIMATE_NOT_PER_SHARE_CASH',literal='616',unit='MILLION_DOLLARS')]

    return dict(profile=NAMED_AB_CURRENT,amount_roles=roles,selected_current_amount=scope['current_amount_literal'],record_date=scope['record_date'],pay_date=scope['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['source_role_proof_ref']),certified_source_cash_share_classes=['A','B'],certified_accounting_cash_share_classes=['A'],other_class_account_position_created=False,other_class_cash_or_quantity_inferred=False,published_percentage_inconsistency_retained_not_used=(scope['ticker']=='FCNCA'),percent_or_aggregate_amount_inference=False,old_amounts_not_discarded=True,original_text_not_rewritten=True,annual_rate_divided_or_inferred=False,current_amount_from_reported_capital=False)



def _named_ab_current_support(payload,entry,facts,listing,pinned):

    scope=_named_ab_scope(facts);same=lambda a,b:_path_sha_ref(a)==_path_sha_ref(b)

    _require(payload.get('named_ab_exact_current_scope')==scope and payload.get('sec_source_transport_profile')==_base().SEC_STATIC_PRIMARY_BODY_PROFILE and facts.get('listing_identity')==scope['listing_identity'] and facts.get('currency')=='USD' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and facts.get('available_at') is None and entry['prior_raw_close']['prior_date']==scope['prior_date'],'R21_ORIGINAL_CURRENT_SCOPE_USD_RAW_CLASSA_UNIT_REQUIRED')

    _require(set(re.findall(r'\bClass\s+([A-Z])\b',listing,re.I))=={'A'},'R21_UNIQUE_ORIGINAL_LISTED_CLASSA_REQUIRED');selected=payload['selected_original_cash_fragment'];_named_ab_semantics(selected['text'],facts,scope['source_publication_date'],listed_common_class='A');proof=json.loads(pinned(scope['source_role_proof_ref']).read_text(encoding='utf-8'));_require(proof['schema']=='EXACT_TWO_NAMED_A_B_COMMON_CURRENT_QUARTER_ROLE_PROOF_R21_R1' and proof['event']=={k:v for k,v in scope.items() if k!='source_role_proof_ref'} and proof['first_publication_at'] is None and proof['engine_available_at'] is None and proof['cash_amount_selected_only_direct_current_literal'] is True and proof['percentage_or_aggregate_cash_inference'] is False and proof['published_comparison_inconsistent_not_used']==(scope['ticker']=='FCNCA'),'R21_PINNED_ROLE_PLAN_AND_UNKNOWN_AVAILABILITY_REQUIRED')

    source=json.loads(pinned(payload['sec_cash_source_custody_ref']).read_text(encoding='utf-8'));full=pinned(_path_sha_ref(proof['new_actual_main_full_ref']));_require(same(source['original_HTTP_ref'],proof['new_actual_main_full_ref']) and same(selected['original_fragment_ref'],proof['current_original_fragment_ref']),'R21_EXACT_CURRENT_FULL_SOURCE_AND_FRAGMENT_REQUIRED');capture=json.loads(pinned(_path_sha_ref(proof['new_actual_capture_ref'])).read_text(encoding='utf-8'));_require(capture['response_status']==200 and capture['actual_HTTP_status_observed'] is True and capture['old_HTTP_status_remains_UNKNOWN'] is True and capture['new_HEADER_prefix_equals_old_exactly'] is True and capture['new_SEC_HEADER_equals_old_exactly'] is True and same(capture['original_HTTP_ref'],proof['new_actual_main_full_ref']) and capture['source_accepted_at_utc']==scope['publication_accepted_at_utc'],'R21_NEW_CAPTURE_REAL_ORIGINAL_HEADER_ONLY_REQUIRED')

    header=pinned(_path_sha_ref(proof['actual_HEADER_ref'])).read_bytes();stamp=re.search(rb'<ACCEPTANCE-DATETIME>([0-9]{14})',header)[1].decode();accepted=pd.Timestamp(stamp).tz_localize('America/New_York').tz_convert('UTC');_require(scope['accession'].encode() in header and re.search(rb'CENTRAL INDEX KEY:\s*0*'+str(scope['issuer_CIK']).encode()+rb'\b',header) and accepted==pd.Timestamp(scope['publication_accepted_at_utc']) and accepted<pd.Timestamp(scope['ex_date'],tz='America/New_York') and accepted<pd.Timestamp('2026-01-01',tz='UTC'),'R21_ACTUAL_ORIGINAL_PREEX_HEADER_CLOCK_REQUIRED')

    with full.open('rb') as f:_require(f.read(65536)==header,'R21_FULL_ORIGINAL_HEADER_BYTES_REQUIRED')

    primary=pinned(_path_sha_ref(proof['original_primary_ref']));parent=proof['original_primary_member']['text_byte_range'];matches=[z for z in proof['physical_original_byte_bindings'] if z['fragment_role']=='original_current_common_cash'];_require(len(matches)==1,'R21_ONE_ORIGINAL_FULL_CURRENT_COMMON_PARAGRAPH_REQUIRED');z=matches[0];a,b=z['new_full_submission_byte_range'];ca,cb=z['old_primary_byte_range'];_require(parent[0]<=a<b<=parent[1]<=full.stat().st_size and 0<=ca<cb<=primary.stat().st_size and b-a==cb-ca and b-a in (616,475) and selected['original_byte_range']==[a,b] and same(z['old_fragment_ref'],proof['current_original_fragment_ref']),'R21_EXACT_CURRENT_PHYSICAL_SCOPE_REQUIRED')

    with full.open('rb') as f:f.seek(a);raw=f.read(b-a)

    with primary.open('rb') as f:f.seek(ca);old=f.read(cb-ca)

    _require(raw==old==pinned(_path_sha_ref(proof['current_original_fragment_ref'])).read_bytes(),'R21_CURRENT_ORIGINAL_PRIMARY_FULL_FRAGMENT_EQUALITY_REQUIRED')

    from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(raw.decode());_require(' '.join(' '.join(parser.parts).split())==scope['original_current_literal'],'R21_NATIVE_ORIGINAL_LITERAL_PROJECTION_REQUIRED')

    ident=json.loads(pinned(payload['frozen_account_identity_ref']).read_text(encoding='utf-8'));rows=[z['original_source_row'] for z in ident['rows'] if pd.Timestamp(z['original_source_row']['effective_start'])<=pd.Timestamp(scope['prior_date'])<=pd.Timestamp(z['original_source_row']['effective_end'])];_require(len(rows)==1 and rows[0]['ticker']==scope['ticker'] and rows[0]['title_of_class']=='CL A' and rows[0]['cusip']==rows[0]['security_id']==scope['original_CUSIP'] and rows[0]['security_id_type']=='CUSIP','R21_UNCHANGED_ORIGINAL_FROZEN_CLASSA_CUSIP_REQUIRED')

    return _VerifiedClass(profile=NAMED_AB_CURRENT,original_frozen_class_literal='CL A',original_CUSIP=scope['original_CUSIP'],ticker=scope['ticker'],row_unchanged=True,source_common_class_literal='Class A Common Stock',source_original_current_common_classes=['A','B'])



def _ordinal_common_scope(facts):

    key=facts.get('ticker','')+'|'+facts.get('exact_frozen_event_key',{}).get('effective_date','');scope=ORDINAL_COMMON_SCOPES.get(key)

    _require(scope is not None and facts.get('ticker')==scope['ticker'] and facts.get('sec_filer_cik')==scope['issuer_CIK'] and facts.get('security_id')==scope['accounting_sid'] and facts['exact_frozen_event_key'].get('ticker')==scope['ticker'],'R22_EXACT_CURRENT_ORDINAL_COMMON_TUPLE_REQUIRED')

    return scope



def _ordinal_common_semantics(text,facts,publication,*,listed_common_class=None):

    scope=_ordinal_common_scope(facts)

    _require(listed_common_class is None and text==scope['original_current_literal'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal(scope['current_amount_literal']) and pd.Timestamp(publication)==pd.Timestamp(scope['source_publication_date']) and re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==scope['original_money_tokens'] and scope['current_ordinal_quarter_literal'] in text and text.startswith('In May 2024, the Company declared'),'R22_ORIGINAL_ORDINAL_QUARTER_MONTH_CURRENT_AMOUNT_DATES_REQUIRED')

    return dict(profile=ORDINAL_CURRENT_COMMON,amount_roles=[dict(role='EXPLICIT_CURRENT_DECLARED_ORDINARY_ORDINAL_QUARTER_CASH',literal=scope['current_amount_literal'])],selected_current_amount=scope['current_amount_literal'],record_date=scope['record_date'],pay_date=scope['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['source_role_proof_ref']),quarter_authority=scope['current_ordinal_quarter_literal'],current_declaration_precision='MONTH_ONLY',current_declared_month=scope['current_month_precision'],exact_board_day_inferred=False,quarterly_word_inserted=False,original_text_not_rewritten=True,current_common_authority='ORIGINAL_CURRENT_DECLARATION_INTERNAL_COMMONSTOCK_DECLARED_TAG',source_clock_role='REAL_SEC_JUNE4_ACCEPTANCE_NOT_MAY_BOARD_DAY_OR_FIRST_PUBLICATION',current_amount_from_reported_concept=False,current_amount_inferred_from_policy=False,old_amounts_not_discarded=True,annual_amount_created=False,annual_rate_divided_or_inferred=False)



def _record_payable_common_scope(facts):

    key=facts.get('ticker','')+'|'+facts.get('exact_frozen_event_key',{}).get('effective_date','');scope=RECORD_PAYABLE_COMMON_SCOPES.get(key)

    _require(scope is not None and facts.get('ticker')==scope['ticker'] and facts.get('sec_filer_cik')==scope['issuer_CIK'] and facts.get('security_id')==scope['accounting_sid'] and facts['exact_frozen_event_key'].get('ticker')==scope['ticker'],'R24_EXACT_RECORD_PAYABLE_COMMON_TUPLE_REQUIRED')

    return scope



def _record_payable_common_semantics(text,facts,publication,*,listed_common_class=None):

    scope=_record_payable_common_scope(facts)

    _require(listed_common_class is None and text==scope['original_current_literal'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal(scope['current_amount_literal']) and pd.Timestamp(publication)==pd.Timestamp(scope['source_publication_date']) and re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==scope['original_money_tokens'] and text.startswith('The Board declared a cash dividend') and 'outstanding common stock to be paid on' in text,'R24_ORIGINAL_CURRENT_COMMON_PAYABLE_RECORD_LITERAL_REQUIRED')

    return dict(profile=RECORD_PAYABLE_CURRENT_COMMON,amount_roles=[dict(role='EXPLICIT_CURRENT_BOARD_COMMON_CASH_PAYABLE_LITERAL',literal=scope['current_amount_literal'])],selected_current_amount=scope['current_amount_literal'],record_date=scope['record_date'],pay_date=scope['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['source_role_proof_ref']),quarter_authority=scope['quarter_member'],current_context_role='RECORD_DATE_NOT_ANNOUNCEMENT_DATE',current_context_instant=scope['current_context_instant'],current_amount_concept=scope['current_amount_concept'],exact_board_day_inferred=False,quarterly_word_inserted=False,current_amount_from_reported_concept=False,current_amount_inferred_from_policy=False,old_amounts_not_discarded=True,annual_amount_created=False,annual_rate_divided_or_inferred=False,original_text_not_rewritten=True,source_clock_role='ACTUAL_NOV4_SEC_ACCEPTANCE_NOT_RECORD_OR_BOARD_DATE')



def _current_common_context_support(payload,entry,facts,pinned,*,record_payable=False):

    scope=_record_payable_common_scope(facts) if record_payable else _ordinal_common_scope(facts);base=_base();same=lambda a,b:_path_sha_ref(a)==_path_sha_ref(b)

    _require(payload.get('record_payable_exact_current_common_scope' if record_payable else 'ordinal_exact_current_common_scope')==scope and payload.get('sec_source_transport_profile')==base.SEC_STATIC_PRIMARY_BODY_PROFILE and facts.get('listing_identity')==scope['listing_identity'] and facts.get('currency')=='USD' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and facts.get('available_at') is None and entry['prior_raw_close']['prior_date']==scope['prior_date'],'R22_EXACT_SCOPE_ORIGINAL_USD_RAW_COMMON_UNIT_REQUIRED')

    proof=json.loads(pinned(scope['source_role_proof_ref']).read_text(encoding='utf-8'));_require(proof['schema']==('EXACT_CURRENT_COMMON_RECORD_DATE_PAYABLE_CONTEXT_PROOF_R24_R1' if record_payable else 'EXACT_CURRENT_ORDINAL_QUARTER_COMMON_MONTH_CONTEXT_ROLE_PROOF_R22_R1') and proof['event']=={k:v for k,v in scope.items() if k!='source_role_proof_ref'} and proof['actual_first_publication_at'] is None and proof['engine_available_at'] is None and proof['reported_capital_values_used'] is False,'R22_PINNED_CURRENT_QUARTER_CONTEXT_PROOF_REQUIRED')

    _require(proof['exact_board_day_inferred'] is False and proof['quarterly_word_inserted'] is False,'R22_ORIGINAL_MONTH_PRECISION_NO_WORD_REWRITE_REQUIRED')

    selected=payload['selected_original_cash_fragment'];(_record_payable_common_semantics if record_payable else _ordinal_common_semantics)(selected['text'],facts,scope['source_publication_date']);source=json.loads(pinned(payload['sec_cash_source_custody_ref']).read_text(encoding='utf-8'));full=pinned(_path_sha_ref(proof['new_actual_main_full_ref']));_require(same(source['original_HTTP_ref'],proof['new_actual_main_full_ref']) and same(selected['original_fragment_ref'],proof['current_original_fragment_ref']),'R22_EXACT_CURRENT_SOURCE_AND_LITERAL_REF_REQUIRED')

    capture=json.loads(pinned(_path_sha_ref(proof['new_actual_capture_ref'])).read_text(encoding='utf-8'));_require(capture['response_status']==200 and capture['actual_HTTP_status_observed'] is True and capture['old_HTTP_status_remains_UNKNOWN'] is True and capture['new_HEADER_prefix_equals_old_exactly'] is True and capture['new_SEC_HEADER_equals_old_exactly'] is True and same(capture['original_HTTP_ref'],proof['new_actual_main_full_ref']) and capture['source_accepted_at_utc']==scope['publication_accepted_at_utc'],'R22_NEW_CURRENT_CAPTURE_ORIGINAL_HEADER_REQUIRED')

    header=pinned(_path_sha_ref(proof['actual_HEADER_ref'])).read_bytes();stamp=re.search(rb'<ACCEPTANCE-DATETIME>([0-9]{14})',header)[1].decode();accepted=pd.Timestamp(stamp).tz_localize('America/New_York').tz_convert('UTC');_require(scope['accession'].encode() in header and re.search(rb'CENTRAL INDEX KEY:\s*0*'+str(scope['issuer_CIK']).encode()+rb'\b',header) and accepted==pd.Timestamp(scope['publication_accepted_at_utc']) and accepted<pd.Timestamp(scope['ex_date'],tz='America/New_York') and accepted<pd.Timestamp('2026-01-01',tz='UTC'),'R22_ACTUAL_ORIGINAL_PREEX_HEADER_CLOCK_REQUIRED')

    with full.open('rb') as stream:_require(stream.read(65536)==header,'R22_FULL_CAPTURE_OLD_HEADER_BYTE_EQUALITY_REQUIRED')

    primary=pinned(_path_sha_ref(proof['original_primary_ref']));parent=proof['original_primary_member']['text_byte_range'];pieces={};spans={}

    tag_role='current_CommonPayable_opening_tag' if record_payable else 'current_CommonStockDeclared_opening_tag';context_role='current_SubsequentEvent_record_context' if record_payable else 'current_SubsequentEvent_May_context'

    for role in ('original_current_common_cash',tag_role,context_role,'original_USD_divide_shares_unit'):

        matches=[z for z in proof['physical_original_byte_bindings'] if z['fragment_role']==role];_require(len(matches)==1,'R22_ONE_ORIGINAL_CURRENT_CONTEXT_UNIT_FRAGMENT_REQUIRED');z=matches[0];a,b=z['new_full_submission_byte_range'];ca,cb=z['old_primary_byte_range'];_require(parent[0]<=a<b<=parent[1]<=full.stat().st_size and 0<=ca<cb<=primary.stat().st_size and b-a==cb-ca and b-a<=2048,'R22_ORIGINAL_BOUNDED_PHYSICAL_FRAGMENT_REQUIRED')

        with full.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)

        with primary.open('rb') as stream:stream.seek(ca);old=stream.read(cb-ca)

        _require(raw==old==pinned(_path_sha_ref(z['old_fragment_ref'])).read_bytes(),'R22_ORIGINAL_PRIMARY_FULL_AND_FRAGMENT_BYTES_REQUIRED');pieces[role]=raw;spans[role]=[a,b]

    cashspan=spans['original_current_common_cash'];_require(selected['original_byte_range']==cashspan and cashspan[0]<=spans[tag_role][0]<spans[tag_role][1]<=cashspan[1],'R22_DECLARED_CONCEPT_INSIDE_CURRENT_ANNOUNCEMENT_REQUIRED')

    from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(pieces['original_current_common_cash'].decode());_require(' '.join(' '.join(parser.parts).split())==scope['original_current_literal'],'R22_ORIGINAL_NATIVE_SPACE_JOIN_LITERAL_REQUIRED')

    tag=pieces[tag_role];context=pieces[context_role];unit=pieces['original_USD_divide_shares_unit']

    _require(all(x in tag for x in ((('name="'+scope['current_amount_concept']+'"').encode() if record_payable else b'name="us-gaap:CommonStockDividendsPerShareDeclared"'),b'unitRef="usdPerShare"',('contextRef="'+scope['current_context_ref']+'"').encode(),b'scale="0"')),'R22_CURRENT_COMMON_DECLARED_CONCEPT_AND_UNIT_REQUIRED')

    if record_payable:

        _require(proof['current_context_role']=='RECORD_DATE_NOT_ANNOUNCEMENT_DATE' and proof['current_context_date_is_record_not_board_or_announcement'] is True and scope['current_context_instant']==scope['record_date'],'R24_RECORD_CONTEXT_NOT_BOARD_OR_ANNOUNCEMENT_REQUIRED')

        _require(all(v in context for v in (('id="'+scope['current_context_ref']+'"').encode(),b'>0001397911</xbrli:identifier>',b'dimension="us-gaap:SubsequentEventTypeAxis">us-gaap:SubsequentEventMember',b'dimension="us-gaap:DividendsAxis">lpla:O2024Q3DividendsMember',('<xbrli:instant>'+scope['current_context_instant']+'</xbrli:instant>').encode())) and b'<xbrli:startDate>' not in context and b'<xbrli:endDate>' not in context,'R24_SAME_CURRENT_CIK_SUBSEQUENT_Q3_RECORD_INSTANT_REQUIRED')

    else:

        _require(all(x in context for x in (('id="'+scope['current_context_ref']+'"').encode(),b'>0000701985</xbrli:identifier>',b'dimension="us-gaap:SubsequentEventTypeAxis">us-gaap:SubsequentEventMember',('<xbrli:startDate>'+scope['current_context_start_date']+'</xbrli:startDate>').encode(),('<xbrli:endDate>'+scope['current_context_end_date']+'</xbrli:endDate>').encode())),'R22_SAME_CURRENT_CIK_SUBSEQUENT_EVENT_DATE_QUARTER_REQUIRED')

    _require(b'<xbrli:unit id="usdPerShare">' in unit and re.search(rb'<xbrli:unitNumerator>\s*<xbrli:measure>iso4217:USD</xbrli:measure>\s*</xbrli:unitNumerator>',unit) and re.search(rb'<xbrli:unitDenominator>\s*<xbrli:measure>xbrli:shares</xbrli:measure>\s*</xbrli:unitDenominator>',unit),'R22_ORIGINAL_USD_DIVIDE_SHARES_UNIT_REQUIRED')

    frozen=base._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer']);_require(frozen is not None,'R22_ORIGINAL_FROZEN_COM_REQUIRED');row=frozen['original_source_row'];dated=base._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned)

    _require(row['ticker']==scope['ticker'] and row['title_of_class']=='COM' and row['cusip']==row['security_id']==scope['original_CUSIP'] and dated['security_uid']=='CUSIP:'+scope['original_CUSIP'] and dated['accounting_sid']==scope['accounting_sid'] and dated['prior_date']==scope['prior_date'] and dated['ex_date']==scope['ex_date'] and dated['same_dated_UID_and_SID'] is True and dated['share_quantity_effect'] is False,'R22_UNCHANGED_ORIGINAL_COM_CUSIP_DATED_RAW_UID_REQUIRED')

    return None





def _ordinal_common_support(payload,entry,facts,pinned):

    return _current_common_context_support(payload,entry,facts,pinned)



def _record_payable_common_support(payload,entry,facts,pinned):

    return _current_common_context_support(payload,entry,facts,pinned,record_payable=True)



def statement_semantics(profile,text,facts,publication,*,listed_common_class=None):
    if profile==HLT_AUTHORIZED_COMMON_UNIT:return _hlt_authorized_semantics(text,facts,publication,listed_common_class=listed_common_class)
    if profile==ALPHABET_CURRENT_ABC:return _alphabet_abc_semantics(text,facts,publication,listed_common_class=listed_common_class)

    if profile==QSR_CURRENT_COMMON_LP:return _qsr_common_lp_semantics(text,facts,publication,listed_common_class=listed_common_class)


    if profile==RECORD_PAYABLE_CURRENT_COMMON:return _record_payable_common_semantics(text,facts,publication,listed_common_class=listed_common_class)

    if profile==ORDINAL_CURRENT_COMMON:return _ordinal_common_semantics(text,facts,publication,listed_common_class=listed_common_class)

    if profile==NAMED_AB_CURRENT:return _named_ab_semantics(text,facts,publication,listed_common_class=listed_common_class)

    if profile==QCOM_CURRENT_CONTEXT:return _qcom_context_semantics(text,facts,publication,listed_common_class=listed_common_class)

    if profile==APO_FIRST_QUARTER:return _apo_first_quarter_semantics(text,facts,publication)

    if profile in (PRMB_CURRENT_CLASS_A,KBR_CURRENT_COMMON):return _r18_static_statement_semantics(profile,text,facts,publication,listed_common_class=listed_common_class)

    if profile==QCOM_CURRENT_POLICY:return _qcom_policy_statement_semantics(text,facts,publication,listed_common_class=listed_common_class)

    if profile==BAC_CURRENT_PERCENT:return _bac_percent_statement_semantics(text,facts,publication,listed_common_class=listed_common_class)

    if profile==ELV_CURRENT_COMMON:return _elv_statement_semantics(text,facts,publication,listed_common_class=listed_common_class)

    """Source literal roles; amounts in comparisons never become payable cash."""

    if profile==EQUAL_NAMED_COMMON_CLASSES: return _meta_statement_semantics(text,facts,publication,listed_common_class)

    if profile in (CLASS_A_CONVERSION_CONTEXT,WORDED_TRANSFER_RECORD):

        return _extended_statement_semantics(profile,text,facts,publication,listed_common_class)

    _require(profile in PROFILES,'R7_UNPLANNED_PROFILE')

    _require(len(text)<=65536 and '\n' not in text,'R7_SINGLE_ORIGINAL_TEXT_PROJECTION_REQUIRED')

    classes={s.upper() for s in re.findall(r'\bClass\s+([A-Z])\b',text,re.I)}

    _require((not classes if listed_common_class is None else classes=={listed_common_class} and listed_common_class in ('A','B','C')),'R7_EXACT_SINGLE_COMMON_CLASS_REQUIRED')

    _require(not re.search(r'\b(?:preferred|depositary|ADS|ADR|adjusted|restated|special dividend|liquidating|return of capital|(?<!common )stock dividend|paid in shares|in kind)\b',text,re.I),'R7_NONORDINARY_OR_DIFFERENT_SHARE_UNIT')

    _require(re.search(r'\b(?:declared|declaration|approved)\b',text,re.I) and re.search(r'\bquarterly\b',text,re.I),'R7_EXPLICIT_QUARTERLY_DECLARATION_REQUIRED')

    _require(re.search(r'\bcommon\s+stock\b',text,re.I),'R7_EXPLICIT_COMMON_STOCK_REQUIRED')

    dates=r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}'

    pays=re.findall(r'\bpayable\s+(?:on\s+)?('+dates+r')',text,re.I)

    records=re.findall(r'\brecord\s+(?:(?:at|as of)\s+(?:the\s+)?(?:close of (?:business|trading)\s+)?)?(?:on\s+)?('+dates+r')',text,re.I)

    _require(len(pays)==len(records)==1,'R7_SINGLE_EXPLICIT_RECORD_AND_PAY_REQUIRED')

    _require(str(pd.Timestamp(pays[0]).date())==facts['pay_date'] and str(pd.Timestamp(records[0]).date())==facts['record_date'],'R7_LITERAL_DATES_CHANGED')

    _require(pd.Timestamp(publication)<pd.Timestamp('2026-01-01') and pd.Timestamp(publication)<=pd.Timestamp(facts['record_date']),'R7_PRE2026_SOURCE_CLOCK_REQUIRED')

    amounts=list(re.finditer(r'\$\s*(\d+(?:\.\d+)?)\s+per\s+(?:(?:common|Class\s+[A-C])\s+)?share\b',text,re.I))

    _require(bool(amounts),'R7_MONETARY_PER_SHARE_LITERAL_REQUIRED')

    # Every dollar token must start one supported explicit per-share amount.

    # Unknown units or a second declaration cannot disappear from the audit.

    money=list(re.finditer(r'\$',text))

    _require([m.start() for m in money]==[m.start() for m in amounts],'R7_UNCLASSIFIED_MONETARY_TOKEN_OR_UNIT')

    if profile==EXACT_COMMON_CLASS:

        _base()._static_submission_cash_statement(text,facts,publication,listed_common_class=listed_common_class)

        _require(len(amounts)==1,'R7_SINGLE_EXACT_CLASS_DECLARATION_REQUIRED')

        roles=[dict(role='CURRENT_QUARTER_DECLARATION',literal=amounts[0].group(1))]

    elif profile==MONETARY_COMMON:

        _require(len(amounts)==1 and not re.search(r'\b(?:from|prior|annual|annualized|increase)\b',text,re.I),'R7_SINGLE_MONETARY_DECLARATION_NO_COMPARISON')

        _require(re.search(r'\bboard\b',text,re.I),'R7_ISSUER_BOARD_DECLARATION_REQUIRED')

        before=text[max(0,amounts[0].start()-140):amounts[0].start()]

        _require(re.search(r'\bdividend\b',before,re.I),'R7_AMOUNT_NOT_CURRENT_DIVIDEND')

        # Cash is an explicit dollar amount per the one listed common class,

        # not a neighbouring cash-flow word or a stock/convertible distribution.

        roles=[dict(role='CURRENT_QUARTER_DECLARATION',literal=amounts[0].group(1))]

    else:

        # A current monetary common-stock declaration is explicit; no neighbouring cash-flow word.

        current=re.search(r'\b(?:approved|declared)\b[^.;]{0,220}?\bquarterly\s+cash\s+dividend\b[^.;$]{0,100}?\bto\s+\$\s*(\d+(?:\.\d+)?)\s+per\s+share\s+from\s+\$\s*(\d+(?:\.\d+)?)\s+per\s+share',text,re.I)

        if current is None:

            current=re.search(r'\bdeclared\b[^.;]{0,100}?\bquarterly\s+dividend\s+of\s+\$\s*(\d+(?:\.\d+)?)\s+per\s+share\s+of\s+'+re.escape(str(facts.get('ticker','')))+r'\s+Common\s+Stock,\s+(?:a\s+)?[0-9]+(?:\.[0-9]+)?%\s+increase\s+from\s+the\s+prior\s+quarterly\s+dividend\s+of\s+\$\s*(\d+(?:\.\d+)?)\s+per\s+share',text,re.I) if facts.get('ticker') else None

        _require(current is not None,'R7_CURRENT_AND_PRIOR_COMPARISON_REQUIRED')

        annual=re.search(r'\bindicated\s+annual\s+rate\s+to\s+\$\s*(\d+(?:\.\d+)?)\s+per\s+share',text,re.I)

        roles=[dict(role='CURRENT_QUARTER_DECLARATION',literal=current.group(1)),dict(role='PRIOR_QUARTER_COMPARISON_NOT_CASH',literal=current.group(2))]

        if annual:roles.append(dict(role='INDICATED_ANNUAL_RATE_NOT_CASH',literal=annual.group(1)))

        _require([m.group(1) for m in amounts]==[r['literal'] for r in roles],'R7_UNCLASSIFIED_OR_REORDERED_AMOUNT')

        _require(Decimal(roles[0]['literal'])>Decimal(roles[1]['literal']),'R7_INCREASE_DIRECTION_CONTRADICTION')

    _require(Decimal(roles[0]['literal'])==Decimal(str(facts['cash_per_raw_share'])),'R7_CURRENT_AMOUNT_CHANGED')

    return dict(profile=profile,amount_roles=roles,selected_current_amount=roles[0]['literal'],

        record_date=facts['record_date'],pay_date=facts['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),

        cash_payment_basis='USD_PER_RAW_OLD_SHARE_AFTER_NATIVE_US_CHARTER_AND_EXACT_RAW_GATES',

        old_amounts_not_discarded=True,annual_rate_divided_or_inferred=False,original_text_not_rewritten=True)



def _statement(profile,text,facts,publication,*,listed_common_class=None):

    if profile==OLD_STATIC:return _base()._static_submission_cash_statement(text,facts,publication,listed_common_class=listed_common_class)

    sem=statement_semantics(profile,text,facts,publication,listed_common_class=listed_common_class)

    return str(pd.Timestamp(publication).date()),sem['selected_current_amount'],facts['pay_date'],facts['record_date']



class _VerifiedClass(dict):pass



def _class_binding(payload,entry,facts,listing,legal_name,pinned):
    if payload['sec_cash_statement_profile']==HLT_AUTHORIZED_COMMON_UNIT:return _hlt_authorized_support(payload,entry,facts,pinned)
    if payload['sec_cash_statement_profile']==ALPHABET_CURRENT_ABC:return _alphabet_abc_support(payload,entry,facts,listing,pinned)

    if payload['sec_cash_statement_profile']==QSR_CURRENT_COMMON_LP:return _qsr_common_lp_support(payload,entry,facts,pinned)


    if payload['sec_cash_statement_profile']==RECORD_PAYABLE_CURRENT_COMMON:return _record_payable_common_support(payload,entry,facts,pinned)

    if payload['sec_cash_statement_profile']==ORDINAL_CURRENT_COMMON:return _ordinal_common_support(payload,entry,facts,pinned)

    if payload['sec_cash_statement_profile']==NAMED_AB_CURRENT:return _named_ab_current_support(payload,entry,facts,listing,pinned)

    if payload['sec_cash_statement_profile']==QCOM_CURRENT_CONTEXT:return _qcom_current_context_support(payload,entry,facts,pinned)

    if payload['sec_cash_statement_profile']==APO_FIRST_QUARTER:return _apo_first_quarter_support(payload,entry,facts,pinned)

    if payload['sec_cash_statement_profile'] in (PRMB_CURRENT_CLASS_A,KBR_CURRENT_COMMON):return _r18_static_current_support(payload,entry,facts,listing,pinned)

    if payload['sec_cash_statement_profile']==QCOM_CURRENT_POLICY:return _qcom_original_policy_support(payload,entry,facts,pinned)

    if payload['sec_cash_statement_profile']==BAC_CURRENT_PERCENT:return _bac_percent_original_support(payload,entry,facts,pinned)

    if payload['sec_cash_statement_profile']==ELV_CURRENT_COMMON:return _elv_current_common_support(payload,entry,facts,listing,pinned)

    if payload['sec_cash_statement_profile'] not in CLASS_PROFILES:return None

    _require(payload.get('sec_source_transport_profile') in (_base().SEC_STATIC_SUBMISSION_PROFILE,_base().SEC_STATIC_PRIMARY_BODY_PROFILE),'R7_CLASS_FULL_STATIC_SUBMISSION_REQUIRED')

    reuse=json.loads(pinned(payload['frozen_account_identity_ref']).read_text(encoding='utf-8-sig'))

    rows=[r['original_source_row'] for r in reuse['rows'] if pd.Timestamp(r['original_source_row']['effective_start'])<=pd.Timestamp(entry['prior_raw_close']['prior_date'])<=pd.Timestamp(r['original_source_row']['effective_end'])]

    _require(len(rows)==1,'R7_EXACT_ORIGINAL_CLASS_INTERVAL_REQUIRED');row=rows[0]

    classes={x.upper() for x in re.findall(r'\bClass\s+([A-Z])\s+Common\s+Stock\b',listing,re.I)}

    profile=payload['sec_cash_statement_profile']

    allowed=((row['title_of_class']=='COM NEW' and not classes) or (row['title_of_class']=='CL A' and classes=={'A'})) if profile==EXACT_COMMON_CLASS else (row['title_of_class']==('COM CL A' if profile==CLASS_A_CONVERSION_CONTEXT else 'CL A') and classes=={'A'})

    if profile==EQUAL_NAMED_COMMON_CLASSES: allowed=allowed and row['ticker']=='META' and row['cusip']=='30303M102'

    _require(allowed and row['ticker']==facts['ticker'],'R7_SOURCE_COMMON_CLASS_AND_ORIGINAL_TITLE_CONFLICT')

    return _VerifiedClass(profile=profile,original_frozen_class_literal=row['title_of_class'],original_CUSIP=row['cusip'],ticker=row['ticker'],source_listing_literal=listing,source_legal_issuer_literal=legal_name,source_ref=payload['same_file_cash_identity_support_ref'],row_unchanged=True)



def _class_allowed(payload,entry,facts,row,binding):

    return isinstance(binding,_VerifiedClass) and payload['sec_cash_statement_profile'] in CLASS_PROFILES and binding['profile']==payload['sec_cash_statement_profile'] and binding['original_frozen_class_literal']==row['title_of_class'] and binding['original_CUSIP']==row['cusip'] and binding['ticker']==facts['ticker']==row['ticker'] and binding['row_unchanged'] is True



def _subject_class(profile,payload,row,listing):
    if profile==ALPHABET_CURRENT_ABC:
        scope=payload.get('alphabet_exact_current_abc_scope',{});return scope in ALPHABET_ABC_SCOPES.values() and row['ticker']==scope['ticker'] and row['title_of_class']==scope['original_frozen_class_literal'] and row['cusip']==scope['original_CUSIP'] and listing==scope['source_listing_literal']


    if profile==PRMB_CURRENT_CLASS_A:return row['title_of_class']=='CLASS A COM SHS' and set(re.findall(r'\bClass\s+([A-Z])\s+Common\s+Stock',listing,re.I))=={'A'}

    if row['title_of_class']=='COM':return True

    if profile not in CLASS_PROFILES:return False

    classes={x.upper() for x in re.findall(r'\bClass\s+([A-Z])\s+Common\s+Stock\b',listing,re.I)}

    return ((row['title_of_class']=='COM NEW' and not classes) or (row['title_of_class']=='CL A' and classes=={'A'})) if profile==EXACT_COMMON_CLASS else (row['title_of_class']==('COM CL A' if profile==CLASS_A_CONVERSION_CONTEXT else 'CL A') and classes=={'A'})



def _binding_fields(profile,text,facts,listed_class,row,binding):

    if profile not in PROFILES:return {}

    semantics=statement_semantics(profile,text,facts,binding['source_statement_date'],listed_common_class=listed_class)

    if profile in (QSR_CURRENT_COMMON_LP,ALPHABET_CURRENT_ABC):binding['currency_basis']=QSR_UNIT_CURRENCY_BASIS

    return dict(source_profile_completion=semantics,source_profile_owner_ref=_ref(__file__),source_base_owner_ref=copy.deepcopy(BASE_SOURCE_REF),

        original_frozen_class_literal=row['title_of_class'],original_frozen_class_rewritten=False,

        source_class_completion_role='EXACT_ORIGINAL_CLASS_LITERAL_PLUS_VERIFIED_ISSUER_COVER_NO_NEW_UID',

        source_completion_profile_scope=copy.deepcopy(SCOPE),

        source_profile_original_class_row=copy.deepcopy(row))



def _cns_common_source_role(payload,entry,facts,transport,raw):

    normal='EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY'

    opt=payload.get('cns_static_common_opt_in')

    if opt is None:return normal

    _require(opt==dict(scope=AAPL_CNS_STATIC_SCOPE,owner_ref=_ref(__file__),base_owner_ref=BASE_SOURCE_REF),

        'R7_AAPL_CNS_EXACT_SOURCE_PROFILE_CODE_SCOPE_REQUIRED')

    cns=facts.get('cns_bank_holiday_record_binding',{});rowkey=facts.get('exact_frozen_event_key',{})

    _require(payload.get('sec_cash_statement_profile')==OLD_STATIC and

        payload.get('sec_source_transport_profile')==_base().SEC_STATIC_SUBMISSION_PROFILE and

        facts.get('ticker')=='AAPL' and facts.get('sec_filer_cik')==320193 and

        facts.get('security_type')=='COMMON_STOCK' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and

        facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and

        facts.get('record_date')==AAPL_CNS_STATIC_SCOPE['record_date'] and facts.get('pay_date')==AAPL_CNS_STATIC_SCOPE['pay_date'] and

        facts.get('ex_date_provenance_role')==cash.NSCC_CNS_RECORD_RESEARCH_ROLE and

        rowkey.get('ticker')=='AAPL' and rowkey.get('effective_date')==AAPL_CNS_STATIC_SCOPE['projected_ex_date'] and

        entry.get('original_unsupported_keys')==[rowkey] and

        rowkey.get('reason')=='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',

        'R7_AAPL_CNS_EXACT_ORIGINAL_COMMON_CASH_KEY_REQUIRED')

    _require(isinstance(transport,dict) and transport.get('schema')=='STATIC_SEC_SAME_ACCESSION_PARENT_AND_EX99_TRANSPORT_V1' and

        transport.get('accession')==AAPL_CNS_STATIC_SCOPE['accession'] and transport.get('issuer_CIK')==320193 and

        transport.get('original_submission_ref',{}).get('sha256')==AAPL_CNS_STATIC_SCOPE['full_submission_sha256'] and

        transport.get('unit_basis')=='ORIGINAL_PRE_EX_CURRENT_COMMON_SHARE_DECLARATION' and

        transport.get('share_quantity_effect') is False and transport.get('source_publication_not_press_dateline') is True and

        pd.Timestamp(transport['accepted_at_utc'])<cash._clock(pd.Timestamp(AAPL_CNS_STATIC_SCOPE['projected_ex_date']),9,30) and

        raw.get('same_dated_UID_and_SID') is True and raw.get('accounting_sid')==facts.get('security_id') and

        raw.get('source_coordinate')=='RAW_ACTUAL_SHARE' and raw.get('ticker')=='AAPL' and

        raw.get('ex_date')==AAPL_CNS_STATIC_SCOPE['projected_ex_date'] and raw.get('new_legal_CUSIP_authority') is False and

        raw.get('share_quantity_effect') is False,'R7_AAPL_CNS_ORIGINAL_FULL_STATIC_AND_RAW_REQUIRED')

    t=_cns_tuple(AAPL_CNS_STATIC_SCOPE['record_date'])

    _require(all(cns.get(k)==v for k,v in t.items() if k not in ('notice_sha256','section_sha256')) and

        cns.get('published_record_date')==facts['record_date'] and cns.get('ticker')=='AAPL' and

        cns.get('security_id')==facts['security_id'] and cns.get('exact_original_frozen_event_key')==rowkey and

        cns.get('notice_source_ref',{}).get('sha256')==t['notice_sha256'] and cns.get('notice_section_ref',{}).get('sha256')==t['section_sha256'] and

        cns.get('notice_section_source_sha256')==t['notice_sha256'] and

        cns.get('issuer_record_source_ref',{}).get('sha256')==facts.get('issuer_source_fingerprint') and

        cns.get('security_identity_source_ref',{}).get('sha256')==facts.get('identity_source_fingerprint') and

        cns.get('available_at') is None and cns.get('actual_exchange_ex_authority')=='UNKNOWN' and

        cns.get('strict_PIT') is False and cns.get('published_record_preserved') is True,

        'R7_AAPL_CNS_EXACT_A9503_SOURCE_AND_UNKNOWN_CLOCK_REQUIRED')

    return cash.NSCC_CNS_RECORD_RESEARCH_ROLE



def _cns_static_entry_allowed(payload,entry,facts):

    """Dispatch only; the full static byte/RAW/notice proof is still required next."""

    return (payload.get('cns_static_common_opt_in')==dict(scope=AAPL_CNS_STATIC_SCOPE,owner_ref=_ref(__file__),base_owner_ref=BASE_SOURCE_REF) and

        payload.get('sec_cash_statement_profile')==OLD_STATIC and

        payload.get('sec_source_transport_profile')==_base().SEC_STATIC_SUBMISSION_PROFILE and

        facts.get('ticker')=='AAPL' and facts.get('sec_filer_cik')==320193 and

        facts.get('record_date')==AAPL_CNS_STATIC_SCOPE['record_date'] and facts.get('pay_date')==AAPL_CNS_STATIC_SCOPE['pay_date'] and

        facts.get('exact_frozen_event_key',{}).get('effective_date')==AAPL_CNS_STATIC_SCOPE['projected_ex_date'] and

        entry.get('original_unsupported_keys')==[facts.get('exact_frozen_event_key')])



def _cns_native_static_allowed(payload,entry,terms=None):

    if payload.get('cns_static_common_opt_in') is None:return False

    terms=payload if terms is None else terms

    b=terms.get('sec_frozen_cash_binding',{});f=terms.get('historical_ex_adjudication_input',{})

    return (b.get('ex_coordinate_role')==cash.NSCC_CNS_RECORD_RESEARCH_ROLE and

        _cns_common_source_role(payload,entry,f,b.get('static_submission_transport_proof'),b.get('static_submission_dated_raw_identity_proof'))==cash.NSCC_CNS_RECORD_RESEARCH_ROLE)



ALLY_STATIC_NYSE_SCOPE=dict(schema='ALLY_EXACT_2025_10_31_ORIGINAL_NYSE_ACRONYM_COVER_COMPATIBILITY_R13',source_draft_ref=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\BAC_ALLY_THREE_SOURCE_TRANSPORT_DRAFT_R1.json',sha256='2dab744746ddd1c5ca572b0c10bdc9572560bd892df8ad09997fc28651681f11'),ticker='ALLY',ex_date='2025-10-31',prior_date='2025-10-30',record_date='2025-10-31',pay_date='2025-11-14',issuer_CIK=40729,original_CUSIP='02005N100',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.ALLY',original_listing_literal='Common Stock, par value $0.01 per share ALLY NYSE',old_default_venue_rules_unchanged=True,share_quantity_effect=False)



def _ally_original_nyse_matches(payload,entry,facts,listing,listings,source,support,pinned):

    """One pinned original cover acronym; the original class/unit/RAW gates continue."""

    opt=payload.get('ally_exact_original_NYSE_acronym_scope')

    if opt is None:

        if payload.get('sec_cash_statement_profile')==ELV_CURRENT_COMMON:

            _require(not listings,'R14_EXACT_ORIGINAL_NYSE_ACRONYM_ONLY_REQUIRED');_elv_current_common_support(payload,entry,facts,listing,pinned);return [('ELV','New York Stock Exchange')]

        return listings

    scope=ALLY_STATIC_NYSE_SCOPE

    _require(opt==scope and payload.get('sec_cash_statement_profile')==MONETARY_COMMON and payload.get('sec_source_transport_profile')==_base().SEC_STATIC_PRIMARY_BODY_PROFILE,'R13_EXACT_ALLY_ORIGINAL_NYSE_SCOPE_REQUIRED')

    _require(not listings and listing==scope['original_listing_literal'] and facts['ticker']=='ALLY' and facts['security_id']==scope['accounting_sid'] and facts['listing_identity']=='NYSE:ALLY' and facts['sec_filer_cik']==source['issuer_CIK']==40729 and facts['exact_frozen_event_key']['ticker']=='ALLY' and facts['exact_frozen_event_key']['effective_date']==scope['ex_date'] and facts['record_date']==scope['record_date'] and facts['pay_date']==scope['pay_date'] and Decimal(str(facts['cash_per_raw_share']))==Decimal('0.30'),'R13_EXACT_ORIGINAL_ALLY_EVENT_AND_VENUE_REQUIRED')

    _require(facts['currency']=='USD' and facts['amount_unit']==cash.USD_PER_RAW_OLD_SHARE and facts['quantity_coordinate']==cash.RAW_OLD_SHARE_COORDINATE and facts['available_at'] is None,'R13_UNCHANGED_USD_RAW_COMMON_UNIT_REQUIRED')

    draft=json.loads(pinned(scope['source_draft_ref']).read_text(encoding='utf-8'));matches=[e for e in draft['events'] if e['ticker']=='ALLY' and e['effective_date']==scope['ex_date']];_require(len(matches)==1,'R13_ONE_ORIGINAL_ALLY_TRANSPORT_EVENT_REQUIRED');e=matches[0]

    original_support=json.loads(pinned(e['support_ref']).read_text(encoding='utf-8'));original_cover=[f for f in original_support['fragments'] if f['fragment_role']=='SAME_FILE_COMMON_LISTING_TABLE'];current_cover=[f for f in support['fragments'] if f['fragment_role']=='SAME_FILE_COMMON_LISTING_TABLE'];same=lambda a,b:all(a[k]==b[k] for k in ('path','sha256'))

    _require(len(original_cover)==len(current_cover)==1 and original_cover[0]['text']==current_cover[0]['text']==listing and same(original_cover[0]['original_fragment_ref'],current_cover[0]['original_fragment_ref']) and original_cover[0]['original_byte_range']==current_cover[0]['original_byte_range'] and same(source['original_HTTP_ref'],e['full_submission_ref']),'R13_EXACT_ORIGINAL_COVER_AND_FULL_SUBMISSION_REQUIRED')

    # The complete original cover is already projected by the native byte validator.

    # Independently retain the original frozen COM/dated mapper before acronym parsing.

    base=_base();frozen=base._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer']);_require(frozen is not None,'R13_ORIGINAL_FROZEN_COMMON_IDENTITY_REQUIRED');row=frozen['original_source_row'];raw=base._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned)

    _require(row['title_of_class']=='COM' and row['ticker']=='ALLY' and row['cusip']==row['security_id']==scope['original_CUSIP'] and raw['security_uid']=='CUSIP:'+scope['original_CUSIP'] and raw['accounting_sid']==scope['accounting_sid'] and raw['prior_date']==scope['prior_date'] and raw['ex_date']==scope['ex_date'] and raw['same_dated_UID_and_SID'] is True and raw['share_quantity_effect'] is False,'R13_ORIGINAL_COM_CUSIP_AND_DATED_RAW_UID_REQUIRED')

    return [('ALLY','New York Stock Exchange')]



class _Extend(ast.NodeTransformer):

    def __init__(self,name):self.name=name;self.counts={}

    def hit(self,key):self.counts[key]=self.counts.get(key,0)+1

    def visit_Compare(self,node):

        self.generic_visit(node)

        if self.name=='_sec_frozen_cash_terms' and ast.unparse(node)=="facts.get('issuer_jurisdiction') != 'US'":
            self.hit('qsr_exact_subject_jurisdiction');return ast.copy_location(ast.parse('not _qsr_subject_jurisdiction(facts,payload)',mode='eval').body,node)

        if self.name=='_sec_primary_html_cash_terms' and ast.unparse(node.left)=='profile' and len(node.ops)==1:

            if isinstance(node.ops[0],ast.Eq) and isinstance(node.comparators[0],ast.Constant) and node.comparators[0].value==OLD_STATIC:

                self.hit('profile_eq');return ast.copy_location(ast.Compare(left=node.left,ops=[ast.In()],comparators=[ast.Tuple(elts=[ast.Constant(v) for v in (OLD_STATIC,*PROFILES)],ctx=ast.Load())]),node)

            if isinstance(node.ops[0],ast.In) and isinstance(node.comparators[0],ast.Tuple) and any(isinstance(v,ast.Constant) and v.value==OLD_STATIC for v in node.comparators[0].elts):

                self.hit('profile_in');node.comparators[0].elts.extend(ast.Constant(v) for v in PROFILES)

        if self.name=='_sec_primary_html_cash_terms' and ast.unparse(node)=="original_row['title_of_class'] != 'COM'":

            self.hit('subject_class');return ast.copy_location(ast.parse('not _subject_class(profile,payload,original_row,listing)',mode='eval').body,node)

        if self.name=='_existing_frozen_common_identity' and ast.unparse(node)=="row['title_of_class'] == 'COM'":

            self.hit('frozen_class');return ast.copy_location(ast.BoolOp(op=ast.Or(),values=[node,ast.parse('_class_allowed(payload,entry,facts,row,source_common_class_binding)',mode='eval').body]),node)

        if self.name=='_sec_frozen_cash_terms' and node.lineno==1187 and ast.unparse(node)=="payload.get('sec_cash_statement_profile') == 'SEC_EXPLICIT_CLASS_A_REGULAR_QUARTERLY_COMMON_SHARE_CASH'":

            self.hit('cns_static_entry_dispatch');return ast.copy_location(ast.BoolOp(op=ast.Or(),values=[node,ast.parse('_cns_static_entry_allowed(payload,entry,facts)',mode='eval').body]),node)

        if self.name=='bind_source_account_descendant' and ast.unparse(node)=="payload.get('sec_frozen_cash_binding', {}).get('sec_cash_statement_profile') != 'SEC_EXPLICIT_CLASS_A_REGULAR_QUARTERLY_COMMON_SHARE_CASH'":

            self.hit('cns_native_static');return ast.copy_location(ast.parse("not (payload.get('sec_frozen_cash_binding',{}).get('sec_cash_statement_profile')=='SEC_EXPLICIT_CLASS_A_REGULAR_QUARTERLY_COMMON_SHARE_CASH' or _cns_native_static_allowed(original_payload,entry,payload))",mode='eval').body,node)

        return node

    def visit_If(self,node):
        self.generic_visit(node)
        if self.name=='_sec_primary_html_cash_terms' and 'not re.fullmatch(_US_CHARTER_STATE_NAMES, US_state, re.I)' in ast.unparse(node.test):
            self.hit('qsr_exact_legal_listing_unit_gate');node.test=ast.Call(func=ast.Name(id='_qsr_source_legal_invalid',ctx=ast.Load()),args=[node.test]+[ast.Name(id=n,ctx=ast.Load()) for n in ('payload','entry','facts','listing','legal_name','US_state','listings','pinned')],keywords=[])
        return node

    def visit_Call(self,node):

        self.generic_visit(node)

        if self.name=='_sec_primary_html_cash_terms' and isinstance(node.func,ast.Name):

            if node.func.id=='dict':

                for keyword in node.keywords:

                    if keyword.arg=='ex_coordinate_role' and isinstance(keyword.value,ast.Constant) and keyword.value.value=='EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY':

                        self.hit('cns_source_role');keyword.value=ast.parse('_cns_common_source_role(payload,entry,facts,submission_proof if submission_profile else None,dated_raw_proof if submission_profile else None)',mode='eval').body

            if node.func.id=='_existing_frozen_common_identity':

                self.hit('identity_call');node.keywords.append(ast.keyword(arg='source_common_class_binding',value=ast.parse('_class_binding(payload,entry,facts,listing,legal_name,pinned)',mode='eval').body))

            elif node.func.id=='_static_submission_cash_statement':

                self.hit('statement_call');node.func=ast.Name(id='_statement',ctx=ast.Load());node.args.insert(0,ast.Name(id='profile',ctx=ast.Load()))

        return node

    def visit_Assign(self,node):

        self.generic_visit(node)

        if self.name=='_sec_primary_html_cash_terms' and len(node.targets)==1 and ast.unparse(node.targets[0])=='cover_classes':
            self.hit('alphabet_exact_original_cover_class');node.value=ast.Call(func=ast.Name(id='_alphabet_cover_classes',ctx=ast.Load()),args=[ast.Name(id='payload',ctx=ast.Load()),ast.Name(id='listing',ctx=ast.Load()),node.value],keywords=[])

        if self.name=='_sec_primary_html_cash_terms' and len(node.targets)==1 and ast.unparse(node.targets[0])=='listings':

            self.hit('ally_exact_NYSE_after_original_listing_projection');node.value=ast.Call(func=ast.Name(id='_ally_original_nyse_matches',ctx=ast.Load()),args=[ast.Name(id=n,ctx=ast.Load()) for n in ('payload','entry','facts','listing')]+[node.value]+[ast.Name(id=n,ctx=ast.Load()) for n in ('source','support','pinned')],keywords=[])

        if self.name=='_sec_primary_html_cash_terms' and len(node.targets)==1 and ast.unparse(node.targets[0])=="facts['sec_frozen_cash_binding']":

            self.hit('binding_fields');extra=ast.parse('if profile in PROFILES: binding.update(_binding_fields(profile,text,facts,listed_class,original_row,binding))').body[0]

            return [ast.copy_location(extra,node),node]

        return node



def _completion_clock(binding,facts):

    """Pure consumer witness; native source parser still proves bytes and identity."""

    profile=binding.get('sec_cash_statement_profile')

    _require(profile in PROFILES,'R7_CLOCK_PROFILE_NOT_PLANNED')

    _require(binding.get('source_profile_owner_ref')==_ref(__file__) and

        binding.get('source_base_owner_ref')==BASE_SOURCE_REF and

        binding.get('source_completion_profile_scope')==SCOPE,'R7_CLOCK_EXACT_CODE_AND_SCOPE_REQUIRED')

    sem=statement_semantics(profile,binding['selected_original_cash_statement'],facts,

        binding['source_statement_date'],listed_common_class=binding.get('source_unique_listed_common_class'))

    _require(binding.get('source_profile_completion')==sem,'R7_CLOCK_ALL_MONETARY_ROLES_REQUIRED')

    row=binding.get('source_profile_original_class_row',{});raw=binding.get('static_submission_dated_raw_identity_proof',{})

    listed=binding.get('source_unique_listed_common_class');title=row.get('title_of_class')

    _require(row.get('ticker')==facts.get('ticker')==raw.get('ticker') and

        row.get('security_id_type')=='CUSIP' and row.get('security_id')==row.get('cusip') and

        isinstance(row.get('cusip'),str) and raw.get('security_uid')=='CUSIP:'+row['cusip'] and

        raw.get('same_dated_UID_and_SID') is True and raw.get('accounting_sid')==facts.get('security_id') and

        raw.get('source_coordinate')=='RAW_ACTUAL_SHARE' and raw.get('new_legal_CUSIP_authority') is False and

        raw.get('share_quantity_effect') is False and binding.get('original_frozen_raw_CUSIP')==row['cusip'] and

        binding.get('original_frozen_class_literal')==title and binding.get('original_frozen_class_rewritten') is False and

        pd.Timestamp(row['effective_start'])<=pd.Timestamp(raw['prior_date'])<=pd.Timestamp(row['effective_end'])<pd.Timestamp('2026-01-01') and

        pd.Timestamp(raw['prior_date'])<pd.Timestamp(raw['ex_date'])<pd.Timestamp('2026-01-01'),

        'R7_CLOCK_UNCHANGED_DATED_RAW_CLASS_AND_UID_REQUIRED')

    allowed=(profile==ALPHABET_CURRENT_ABC and title==_alphabet_abc_scope(facts)['original_frozen_class_literal'] and listed==_alphabet_abc_scope(facts)['listed_common_class']) or (profile==PRMB_CURRENT_CLASS_A and title=='CLASS A COM SHS' and listed=='A') or (title=='COM' and profile not in CLASS_PROFILES) or (profile==EXACT_COMMON_CLASS and

        ((title=='COM NEW' and listed is None) or (title=='CL A' and listed=='A'))) or (profile==CLASS_A_CONVERSION_CONTEXT and title=='COM CL A' and listed=='A') or (profile in (EQUAL_NAMED_COMMON_CLASSES,NAMED_AB_CURRENT) and title=='CL A' and listed=='A')

    _require(allowed,'R7_CLOCK_EXACT_ORIGINAL_COMMON_CLASS_REQUIRED')

    if profile in (PRMB_CURRENT_CLASS_A,KBR_CURRENT_COMMON):

        scope=PRMB_CURRENT_SCOPE if profile==PRMB_CURRENT_CLASS_A else KBR_CURRENT_SCOPE

        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==scope['issuer_CIK'],'R18_EXACT_CURRENT_STATIC_CLASS_CUSIP_DATED_UID_REQUIRED')

    if profile==RECORD_PAYABLE_CURRENT_COMMON:

        scope=_record_payable_common_scope(facts);proof=json.loads(_base()._pin(scope['source_role_proof_ref']).read_text(encoding='utf-8'));tr=binding.get('static_submission_transport_proof',{})

        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==scope['issuer_CIK'] and _path_sha_ref(tr.get('original_submission_ref',{}))==_path_sha_ref(proof['new_actual_main_full_ref']) and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(scope['publication_accepted_at_utc']) and proof['current_context_role']=='RECORD_DATE_NOT_ANNOUNCEMENT_DATE','R24_REAL_ACCEPTANCE_RECORD_CONTEXT_AND_EXACT_DATED_COMMON_UID_REQUIRED')

    if profile==ORDINAL_CURRENT_COMMON:

        scope=_ordinal_common_scope(facts);proof=json.loads(_base()._pin(scope['source_role_proof_ref']).read_text(encoding='utf-8'));tr=binding.get('static_submission_transport_proof',{})

        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==scope['issuer_CIK'] and _path_sha_ref(tr.get('original_submission_ref',{}))==_path_sha_ref(proof['new_actual_main_full_ref']) and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(scope['publication_accepted_at_utc']),'R22_REAL_ACCEPTANCE_CLOCK_AND_EXACT_DATED_COMMON_UID_REQUIRED')

    if profile==NAMED_AB_CURRENT:

        scope=_named_ab_scope(facts);proof=json.loads(_base()._pin(scope['source_role_proof_ref']).read_text(encoding='utf-8'));tr=binding.get('static_submission_transport_proof',{})

        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==scope['issuer_CIK'] and _path_sha_ref(tr.get('original_submission_ref',{}))==_path_sha_ref(proof['new_actual_main_full_ref']) and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(scope['publication_accepted_at_utc']),'R21_EXACT_ORIGINAL_HEADER_CLASSA_DATED_UID_AND_SID_REQUIRED')

    if profile==QCOM_CURRENT_CONTEXT:

        scope=_qcom_context_scope(facts);proof=json.loads(_base()._pin(scope['source_role_proof_ref']).read_text(encoding='utf-8'));tr=binding.get('static_submission_transport_proof',{})

        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==804328 and _path_sha_ref(tr.get('original_submission_ref',{}))==_path_sha_ref(proof['new_actual_main_full_ref']) and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(scope['publication_accepted_at_utc']),'R20_EXACT_ORIGINAL_HEADER_DATED_COM_CURRENT_CONTEXT_CLOCK_REQUIRED')

    if profile==APO_FIRST_QUARTER:

        scope=APO_FIRST_QUARTER_SCOPE;proof=json.loads(_base()._pin(scope['source_role_proof_ref']).read_text(encoding='utf-8'));tr=binding.get('static_submission_transport_proof',{})

        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==1858681 and _path_sha_ref(tr.get('original_submission_ref',{}))==_apo_exact_capture_equivalence(proof,_base()._pin) and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(scope['publication_accepted_at_utc']),'R19_REAL_APO_MAIN_HEADER_AND_DATED_RAW_CUSIP_REQUIRED')

    if profile==QCOM_CURRENT_POLICY:

        scope=QCOM_POLICY_SCOPE;proof=json.loads(_base()._pin(scope['source_role_proof_ref']).read_text(encoding='utf-8'));tr=binding.get('static_submission_transport_proof',{})

        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==scope['issuer_CIK'] and _path_sha_ref(tr.get('original_submission_ref',{}))==_path_sha_ref(proof['source_original_full_submission_ref']) and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(scope['publication_accepted_at_utc']),'R17_ORIGINAL_TRANSPORT_HEADER_AND_EXACT_DATED_COM_REQUIRED')

    if profile==BAC_CURRENT_PERCENT:

        scope=BAC_PERCENT_SCOPE;proof=json.loads(_base()._pin(scope['source_role_proof_ref']).read_text(encoding='utf-8'));tr=binding.get('static_submission_transport_proof',{});same=lambda a,b:all(a.get(k)==b.get(k) for k in ('path','sha256'))

        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==scope['issuer_CIK'] and same(tr.get('original_submission_ref',{}),proof['original_same_full_submission_ref']) and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(scope['publication_accepted_at_utc']),'R16_ORIGINAL_TRANSPORT_HEADER_AND_EXACT_DATED_COM_REQUIRED')

    if profile==EQUAL_NAMED_COMMON_CLASSES:

        tr=binding.get('static_submission_transport_proof',{});src=META_NAMED_COMMON_SCOPE

        _require(row.get('ticker')==src['ticker'] and row.get('cusip')==src['original_CUSIP'] and raw.get('accounting_sid')==src['raw_accounting_sid'] and raw.get('prior_date')==src['prior_date'] and raw.get('ex_date')==src['ex_date'] and binding.get('sec_filer_cik')==src['sec_filer_cik'] and tr.get('original_submission_ref')==src['full_submission_ref'] and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(src['actual_accepted_at_utc']),'R9_ACTUAL_STATIC_SOURCE_AND_ORIGINAL_RAW_CLASS_BINDING_REQUIRED')

    if profile==QSR_CURRENT_COMMON_LP:
        scope=_qsr_common_lp_scope(facts);proof=json.loads(_base()._pin(scope['source_role_proof_ref']).read_text(encoding='utf-8'));tr=binding.get('static_submission_transport_proof',{})
        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==scope['issuer_CIK'] and facts.get('issuer_jurisdiction')=='CA' and binding.get('currency_basis')==QSR_UNIT_CURRENCY_BASIS and _path_sha_ref(tr.get('original_submission_ref',{}))==_path_sha_ref(proof['new_actual_main_full_ref']) and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(scope['publication_accepted_at_utc']) and pd.Timestamp(scope['source_available_at'])<pd.Timestamp(raw['prior_date'],tz='America/New_York')+pd.Timedelta(hours=16),'R27_SOURCE_AND_UNIT_CLOCK_REAL_CANADA_CUSIP_DATED_UID_REQUIRED')

    if profile==ALPHABET_CURRENT_ABC:
        scope=_alphabet_abc_scope(facts);proof=json.loads(_base()._pin(scope['source_role_proof_ref']).read_text(encoding='utf-8'));tr=binding.get('static_submission_transport_proof',{})
        _require(row.get('cusip')==scope['original_CUSIP'] and raw.get('prior_date')==scope['prior_date'] and raw.get('ex_date')==scope['ex_date'] and binding.get('sec_filer_cik')==1652044 and _path_sha_ref(tr.get('original_submission_ref',{}))==_path_sha_ref(proof['new_actual_main_full_ref']) and pd.Timestamp(tr.get('accepted_at_utc'))==pd.Timestamp(scope['publication_accepted_at_utc']) and pd.Timestamp(scope['source_available_at'])<pd.Timestamp(raw['prior_date'],tz='America/New_York')+pd.Timedelta(hours=16),'R28_REAL_CURRENT_UNIT_POLICY_SOURCE_CLOCK_AND_ORIGINAL_A_C_UID_REQUIRED')

    return True



def _completion_listed_class(binding,facts):
    if binding.get('sec_cash_statement_profile')==ALPHABET_CURRENT_ABC:
        scope=_alphabet_abc_scope(facts);return _completion_clock(binding,facts) and binding.get('original_frozen_class_literal')==scope['original_frozen_class_literal'] and binding.get('source_unique_listed_common_class')==scope['listed_common_class']


    if binding.get('sec_cash_statement_profile')==PRMB_CURRENT_CLASS_A:return _completion_clock(binding,facts) and binding.get('original_frozen_class_literal')=='CLASS A COM SHS' and binding.get('source_unique_listed_common_class')=='A'

    return (binding.get('sec_cash_statement_profile') in CLASS_PROFILES and

        _completion_clock(binding,facts) and

        binding['original_frozen_class_literal']==('COM CL A' if binding.get('sec_cash_statement_profile')==CLASS_A_CONVERSION_CONTEXT else 'CL A') and

        binding.get('source_unique_listed_common_class')=='A')



class _CashExtend(ast.NodeTransformer):

    def __init__(self):self.counts={}

    def hit(self,key):self.counts[key]=self.counts.get(key,0)+1

    def visit_Assign(self,node):

        self.generic_visit(node)

        if node.lineno==618 and len(node.targets)==1 and ast.unparse(node.targets[0])=='jurisdiction_ok':
            self.hit('qsr_exact_cash_jurisdiction');node.value=ast.parse('_qsr_cash_jurisdiction(facts)',mode='eval').body

        if len(node.targets)==1 and ast.unparse(node.targets[0])=='frozen_common_roles':

            self.hit('roles');node.value.keys.extend(ast.Constant(v) for v in PROFILES)

            node.value.values.extend(ast.Constant('STATIC_SUBMISSION_PUBLIC_ACCEPTANCE_DAY_NOT_BOARD_DATE') for _ in PROFILES)

        if len(node.targets)==1 and ast.unparse(node.targets[0])=='profile' and ast.unparse(node.value)=="binding.get('sec_cash_statement_profile')":

            self.hit('witness');return [node,ast.parse('if profile in PROFILES: _completion_clock(binding,facts)').body[0]]

        return node

    def visit_Compare(self,node):

        self.generic_visit(node)

        if isinstance(node.left,ast.Call) and ast.unparse(node.left)=="binding.get('currency_basis')" and node.lineno==632:
            self.hit('qsr_exact_cash_currency_basis');node.comparators[0]=ast.Call(func=ast.Name(id='_qsr_cash_currency_basis',ctx=ast.Load()),args=[ast.Name(id='binding',ctx=ast.Load()),ast.Name(id='facts',ctx=ast.Load()),node.comparators[0]],keywords=[])

        if ast.unparse(node)=="profile == 'STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION'":

            self.hit('static_profile');return ast.copy_location(ast.Compare(left=node.left,ops=[ast.In()],comparators=[ast.Tuple(elts=[ast.Constant(v) for v in (OLD_STATIC,*PROFILES)],ctx=ast.Load())]),node)

        if ast.unparse(node)=="binding.get('original_frozen_class_literal') == 'COM'":

            self.hit('listed_class');return ast.copy_location(ast.BoolOp(op=ast.Or(),values=[node,ast.parse('_completion_listed_class(binding,facts)',mode='eval').body]),node)

        return node



def _cns_tuple(record):

    """Exactly two original NSCC source tuples; neither is exchange authority."""

    if record=='2025-11-11':

        return dict(cns_projected_record_date='2025-11-10',notice_number='a9648',notice_publication_date='2025-10-02',notice_page_zero_based=1,

            notice_primary_url='https://www.dtcc.com/-/media/Files/pdf/2025/10/2/a9648.pdf',

            actual_capture_url='https://files.dtcc.com/download/assets/a9648/5d1b3be0ceb411f08977de3dd66d09b0',

            notice_sha256=cash.NSCC_CNS_2025_NOTICE_SHA256,section_sha256=cash.NSCC_CNS_2025_SECTION_SHA256)

    if record=='2024-11-11':

        return dict(cns_projected_record_date='2024-11-08',notice_number='a9503',notice_publication_date='2024-10-11',notice_page_zero_based=2,

            notice_primary_url='https://www.dtcc.com/-/media/Files/pdf/2024/10/11/a9503.pdf',

            actual_capture_url='https://web.archive.org/web/20241102074151id_/https://www.dtcc.com/-/media/Files/pdf/2024/10/11/a9503.pdf',

            notice_sha256='f8c59501fe1a7473b2dd19d6bd4cf99d5aafc68102f8214bd7c829bb290c5396',

            section_sha256='6b48426e16ab34516a95ee69584d8c95222ca1b58ac192c9841b6bc5abe97b27')

    raise ValueError('NSCC_CNS_EXPLICIT_PRE2026_RECORD_PROJECTION_REQUIRED')



class _CnsExtend(ast.NodeTransformer):

    def __init__(self):self.counts={}

    def hit(self,key):self.counts[key]=self.counts.get(key,0)+1

    def visit_Compare(self,node):

        self.generic_visit(node);text=ast.unparse(node)

        if text=="record_date != '2025-11-11'":

            self.hit('record_whitelist');return ast.copy_location(ast.parse("record_date not in ('2024-11-11','2025-11-11')",mode='eval').body,node)

        fields={'cns_projected_record_date':'2025-11-10','notice_number':'a9648','notice_publication_date':'2025-10-02','notice_primary_url':'https://www.dtcc.com/-/media/Files/pdf/2025/10/2/a9648.pdf','actual_capture_url':'https://files.dtcc.com/download/assets/a9648/5d1b3be0ceb411f08977de3dd66d09b0'}

        for key,value in fields.items():

            if text==f"binding.get({key!r}) != {value!r}":

                self.hit('notice_field');node.comparators=[ast.parse(f'_cns_tuple(record_date)[{key!r}]',mode='eval').body];return node

        if text=="binding['notice_page_zero_based'] != 1":

            self.hit('notice_field');node.comparators=[ast.parse("_cns_tuple(record_date)['notice_page_zero_based']",mode='eval').body];return node

        sha_comparisons={"binding['notice_source_ref']['sha256'] != NSCC_CNS_2025_NOTICE_SHA256":'notice_sha256',"binding['notice_section_ref']['sha256'] != NSCC_CNS_2025_SECTION_SHA256":'section_sha256',"binding.get('notice_section_source_sha256') != NSCC_CNS_2025_NOTICE_SHA256":'notice_sha256'}

        if text in sha_comparisons:

            self.hit('source_sha');node.comparators=[ast.parse(f'_cns_tuple(record_date)[{sha_comparisons[text]!r}]',mode='eval').body]

        return node



def _cash_owner():

    _require(_ref(cash.__file__)['sha256']==CASH_SHA,'R7_CASH_NATIVE_OWNER_CHANGED')

    ns=dict(vars(cash));ns.update(PROFILES=PROFILES,_cns_tuple=_cns_tuple,_completion_clock=_completion_clock,_completion_listed_class=_completion_listed_class,_qsr_cash_jurisdiction=_qsr_cash_jurisdiction,_qsr_cash_currency_basis=_qsr_cash_currency_basis)

    for name,value in tuple(ns.items()):

        if isinstance(value,FunctionType) and value.__globals__ is cash.__dict__:

            clone=FunctionType(value.__code__,ns,name,value.__defaults__,value.__closure__);clone.__kwdefaults__=value.__kwdefaults__;ns[name]=clone

    tree=ast.parse(Path(cash.__file__).read_text(encoding='utf-8'))

    node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='adjudicate_post_verified_cash_ex'))

    tx=_CashExtend();node=tx.visit(node);ast.fix_missing_locations(node)

    _require(tx.counts==dict(roles=1,witness=1,static_profile=2,listed_class=1,qsr_exact_cash_jurisdiction=1,qsr_exact_cash_currency_basis=1),'R7_CASH_AST_ANCHOR_CHANGED:'+str(tx.counts))

    exec(compile(ast.Module(body=[node],type_ignores=[]),__file__,'exec'),ns)

    proof=dict(adjudicate_post_verified_cash_ex=tx.counts)

    node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_cns_bank_holiday_record_binding'))

    tx=_CnsExtend();node=tx.visit(node);ast.fix_missing_locations(node)

    _require(tx.counts==dict(record_whitelist=1,notice_field=6,source_sha=3),'R7_CNS_AST_ANCHOR_CHANGED:'+str(tx.counts))

    exec(compile(ast.Module(body=[node],type_ignores=[]),__file__,'exec'),ns)

    proof['validate_cns_bank_holiday_record_binding']=tx.counts

    return SimpleNamespace(**ns),proof



def adjudicate_post_verified_cash_ex(*args,**kwargs):

    owner,_=_cash_owner();return owner.adjudicate_post_verified_cash_ex(*args,**kwargs)







MSFT_HTML_SIX_SCOPE = {'profile': 'MSFT_ORIGINAL_ARCHIVE_QUARTERLY_DECLARATION_WITH_SEPARATE_PREEX_SEC_CASH_COMMON_USD_SHARE_UNIT_R10', 'material_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\MSFT_SIX_DECLARATION_CLASS_CASH_USD_IDENTITY_BINDING_SOURCE_PROOF_R1.json', 'sha256': '65992f6b9c651f7aae4b52994ddcdc59663daa869e955ed8f21d944fa3951b2c'}, 'exact_ex_dates': ['2023-05-17', '2024-02-14', '2024-08-15', '2025-02-20', '2025-05-15', '2025-08-21'], 'ticker': 'MSFT', 'issuer_cik': 789019, 'original_CUSIP': '594918104', 'old_source_profiles_unchanged': True, 'alpha_or_label_expansion': False}

MSFT_UNIT_SUPPORT_SCHEMA = "MSFT_SIX_SEPARATE_PREEX_SEC_CASH_COMMON_USD_SHARE_UNIT_SUPPORT_R10"



def _original_common_cash_usd_unit(unit,pinned,*,issuer_cik,concept,class_literal):

    header=pinned(unit['accepted_header_ref']).read_bytes();_require(re.search(rb'CENTRAL INDEX KEY:\s*0*'+str(issuer_cik).encode()+rb'\b',header) is not None and re.search(rb'<ACCEPTANCE-DATETIME>[0-9]{14}',header) is not None,'R10_REAL_PREEX_MSFT_SEC_UNIT_HEADER_REQUIRED')

    accepted=re.search(rb'<ACCEPTANCE-DATETIME>([0-9]{14})',header).group(1).decode();_require(pd.to_datetime(accepted,format='%Y%m%d%H%M%S').tz_localize('America/New_York').tz_convert('UTC')==pd.Timestamp(unit['accepted_at_utc']) and unit['source_form'] in ('10-Q','10-K') and re.search(rb'ACCESSION NUMBER:\s*'+re.escape(unit['accession'].encode()),header) is not None,'R10_ACTUAL_SEC_ACCEPTANCE_AND_ACCESSION_REQUIRED')

    body=pinned(unit['source_document_ref']);a,b=unit['capital_fragment_byte_range'];_require(0<=a<b<=body.stat().st_size and b-a<=65536,'R10_BOUNDED_COMMON_CASH_UNIT_ROW_REQUIRED')

    with body.open('rb') as h:h.seek(a);original=h.read(b-a)

    _require(original==pinned(unit['capital_fragment_ref']).read_bytes() and b'name="'+concept.encode()+b'"' in original,'R10_ORIGINAL_COMMON_CASH_XBRL_ROW_REQUIRED')

    from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(original.decode('utf-8'));visible=' '.join(' '.join(parser.parts).split());_require(visible==unit['original_capital_row_literal'] and class_literal in visible,'R10_ORIGINAL_CASH_COMMON_CLASS_TEXT_REQUIRED')

    units=unit['USD_per_common_share_unit_metadata'];_require(len(units)==1,'R10_ONE_ORIGINAL_USD_SHARE_UNIT_REQUIRED');u=units[0]

    a,b=u['byte_start'],u['byte_end'];_require(0<=a<b<=body.stat().st_size and b-a<=4096,'R10_BOUNDED_ORIGINAL_UNIT_DEFINITION_REQUIRED')

    with body.open('rb') as h:h.seek(a);unit_bytes=h.read(b-a)

    _require(unit_bytes.decode('utf-8')==u['original_unit_markup'],'R10_ORIGINAL_UNIT_DEFINITION_CHANGED')

    import xml.etree.ElementTree as ET

    root=ET.fromstring(b'<root xmlns:xbrli="http://www.xbrl.org/2003/instance">'+unit_bytes+b'</root>')[0];local=lambda tag:tag.rsplit('}',1)[-1];children=list(root)

    _require(local(root.tag)=='unit' and root.attrib.get('id')==u['id'] and len(children)==1 and local(children[0].tag)=='divide','R10_ORIGINAL_DIVIDED_UNIT_REQUIRED')

    parts=list(children[0]);_require(len(parts)==2 and [local(x.tag) for x in parts]==['unitNumerator','unitDenominator'] and all(len(x)==1 and local(x[0].tag)=='measure' for x in parts) and [x[0].text for x in parts]==['iso4217:USD','xbrli:shares'],'R10_USD_NUMERATOR_PER_SHARE_DENOMINATOR_REQUIRED')

    cells=re.findall(rb'<ix:nonFraction\b[^>]*\bname="'+re.escape(concept.encode())+rb'"[^>]*>',original)

    _require(cells and all(re.search(rb'\bunitRef="'+re.escape(u['id'].encode())+rb'"',x) for x in cells),'R10_UNIT_TIED_TO_ORIGINAL_COMMON_CASH_CONCEPT_REQUIRED')

    return u



class _VerifiedMsftSupport(dict):pass



def _msft_common_support(payload,entry,support,pinned):

    """Validate separate pre-ex class/USD source bytes before monetary parsing."""

    src=MSFT_HTML_SIX_SCOPE

    _require(support.get('schema')==MSFT_UNIT_SUPPORT_SCHEMA and support.get('scope')==src and support.get('source_material_ref')==src['material_ref'],'R10_EXACT_MSFT_UNIT_SOURCE_SCOPE_REQUIRED')

    key=support.get('ex_date');_require(key in src['exact_ex_dates'] and support.get('ticker')=='MSFT','R10_EXACT_SIX_MSFT_SOURCE_EVENTS_REQUIRED')

    mat=json.loads(pinned(src['material_ref']).read_text(encoding='utf-8'));matches=[e for e in mat['entries'] if e['ticker']=='MSFT' and e['effective_date']==key];_require(len(matches)==1,'R10_UNIQUE_SOURCE_MATERIAL_EVENT_REQUIRED');e=matches[0]

    unit=e['independent_cash_common_class_basis'];ex=pd.Timestamp(key).tz_localize('America/New_York')+pd.Timedelta(hours=9,minutes=30)

    _require(pd.Timestamp(e['source_published_metadata_utc'])<ex and pd.Timestamp(e['original_version_available_no_later_than'])<ex and pd.Timestamp(unit['accepted_at_utc'])<ex and ex<pd.Timestamp('2026-01-01',tz='America/New_York'),'R10_PUBLICATION_CAPTURE_AND_SEPARATE_UNIT_PREEX_REQUIRED')

    _require(e['original_frozen_prior_row']['title_of_class']=='COM' and e['original_frozen_prior_row']['cusip']=='594918104' and e['original_frozen_prior_row']['security_id']=='594918104' and e['original_frozen_prior_date']==entry['prior_raw_close']['prior_date'] and e['ex_and_prior_RAW_identity']['same_dated_cusip_and_accounting_sid'] is True and e['original_announcement_cash_or_common_words_added'] is False and unit['current_event_dividend_amount_from_capital_row'] is False,'R10_ORIGINAL_COMMON_UID_AND_CURRENT_AMOUNT_AUTHORITY_REQUIRED')

    u=_original_common_cash_usd_unit(unit,pinned,issuer_cik=789019,concept='us-gaap:CommonStockDividendsPerShareDeclared',class_literal='Cash dividends declared per common share')

    original_row=e['original_frozen_prior_row'];_require(entry['identity_binding']['ticker']=='MSFT' and entry['identity_binding']['listing_identity']=='NASDAQ:MSFT' and entry['identity_binding']['issuer']==original_row['issuer_name'] and support.get('original_CUSIP')==original_row['cusip'] and support.get('source_material_event_fingerprint')==_base()._hash(e),'R10_EXACT_FROZEN_SOURCE_EVENT_IDENTITY_REQUIRED')

    _require(e['source_available_at_for_engine'] is None and e['model_or_label_input_authority_granted'] is False and e['issuer_CIK_not_security_UID'] is True and e['new_CUSIP_or_ticker_identity_invented'] is False,'R10_SOURCE_ROLE_CANNOT_GRANT_INPUT_OR_NEW_IDENTITY')

    # Only the concept/class and original unit definition are consumed; no capital amount.

    return _VerifiedMsftSupport(profile=src['profile'],source_common_class_literal='Common Stock',source_CUSIP='594918104',original_frozen_class_literal='COM',status='PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT',no_class_alias=True,original_frozen_class_rewritten=False,source_legal_issuer_literal=entry['identity_binding']['issuer'],source_listing_identity='NASDAQ:MSFT',source_US_context_literal='EXPLICIT_SEPARATE_SEC_USD_PER_COMMON_SHARE_UNIT',source_material_event=e,source_material_ref=src['material_ref'],available_at=None,historical_availability_authority='UNKNOWN',share_quantity_effect=False,USD_unit_original_metadata=u)



def _msft_announcement_terms(source,binding,projection,pub,capture,full_body):

    """New article format only; all ex/price/account adjudication remains native."""

    _require(isinstance(binding,_VerifiedMsftSupport) and full_body is not None,'R10_VALIDATED_MSFT_SEPARATE_UNIT_BINDING_REQUIRED')

    e=binding['source_material_event'];_require(len(source.get('cash_fragments',[]))==1,'R10_ONE_UNMODIFIED_ORIGINAL_ANNOUNCEMENT_REQUIRED');item=source['cash_fragments'][0];text=projection(item)

    _require(text==e['declaration_literal'] and hashlib.sha256(text.encode()).hexdigest()==e['declaration_literal_sha256'] and text.count('$')==1 and not re.search(r'\bpreferred|ADR|ADS|converted|adjusted|restated|annual\b',text,re.I),'R10_EXACT_ORIGINAL_MONETARY_ANNOUNCEMENT_REQUIRED')

    dates=r'([A-Za-z.]+ \d{1,2}, 20\d{2})';m=re.search(r'\bdeclared a quarterly dividend of \$(\d+\.\d+) per share\. The dividend is payable '+dates+r', to shareholders of record on '+dates+r'\. The ex-dividend date will be '+dates+r'\.',text)

    _require(m is not None and Decimal(m.group(1))==Decimal(e['declared_amount_literal']) and str(pd.Timestamp(m.group(2)).date())==e['announced_pay_date'] and str(pd.Timestamp(m.group(3)).date())==e['issuer_record_date'] and str(pd.Timestamp(m.group(4)).date())==e['issuer_announced_ex_dividend_date'],'R10_ORIGINAL_AMOUNT_RECORD_PAY_EX_OBSERVATION_REQUIRED')

    _require(pub==pd.Timestamp(e['source_published_metadata_utc']).tz_convert('UTC').normalize().tz_localize(None) and capture==pd.Timestamp(e['original_version_available_no_later_than']),'R10_TRUE_ARCHIVED_PUBLICATION_AND_CAPTURE_CLOCK_REQUIRED')

    return dict(issuer=binding['source_legal_issuer_literal'],ticker='MSFT',listing='NASDAQ:MSFT',amount=float(Decimal(m.group(1))),record=e['issuer_record_date'],pay=e['announced_pay_date'],publication=str(pub.date()),available=None,currency_basis='EXPLICIT_USD',source_currency_explicit_USD=False,source_currency_separate_SEC_USD_unit=True,body_ref=copy.deepcopy(item['fragment_ref']),header_ref=copy.deepcopy(source['dated_header_observations'][0]['fragment_ref']),source_paragraph=text,source_original_typed_text_digest=hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest(),source_original_typed_text_digest_recipe='UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT',source_declared_ex_date=None,issuer_observed_ex_date=e['issuer_announced_ex_dividend_date'],issuer_observed_ex_role='NONOPERATIVE_ISSUER_OBSERVATION_RETAINED_NORMAL_RESEARCH_CLOCK',source_US_context_literal=binding['source_US_context_literal'],original_source_unit_literal='per share',source_subject_role=MSFT_HTML_SIX_SCOPE['profile'],source_registrant_name_literal=e['issuer_name_original'],source_common_cover_class_literal='Common Stock',source_cash_classification_literal='quarterly',source_full_HTTP_sha256=source['received_http_bytes_sha256'],source_full_HTTP_bytes=source['received_bytes'],full_HTTP_body_locally_available=True,current_transport_capture_utc=str(capture.tz_convert('UTC')),capture_is_not_available_at=True,source_original_publication_utc=e['source_published_metadata_utc'],source_publication_calendar_date_role='ORIGINAL_ARCHIVED_HEAD_UTC_DATE_NOT_BOARD_DATE',separate_common_cash_unit_available_utc=binding['source_material_event']['independent_cash_common_class_basis']['accepted_at_utc'],historical_availability_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',actual_SEC_HTTP_or_header_authority=False,source_fragment_physical_sha256=item['fragment_ref']['sha256'],source_text_utf8_sha256=item['visible_text_utf8_sha256'])





HON_HTML_TWO_SCOPE = dict(profile='HON_ORIGINAL_ARCHIVE_EXPLICIT_CURRENT_QUARTER_WITH_ANNUAL_COMPARISONS_AND_SEPARATE_PREEX_COMMON_USD_UNIT_R11',material_ref=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\HON_FOUR_ORIGINAL_CASH_DECLARATION_SOURCE_DRAFTS_R1.json',sha256='d30ec2df7c17498b9a533117918c36a4a385ea2d97078b6aa9335ecbc1fc7a47'),exact_ex_dates=['2024-11-15','2025-02-28'],ticker='HON',issuer_cik=773840,original_CUSIP='438516106',old_source_profiles_unchanged=True,alpha_or_label_expansion=False)

HON_UNIT_SUPPORT_SCHEMA='HON_TWO_SEPARATE_PREEX_SEC_CASH_COMMON_USD_SHARE_UNIT_SUPPORT_R11'

class _VerifiedHonSupport(dict):pass



def _hon_common_support(payload,entry,support,pinned):

    scope=HON_HTML_TWO_SCOPE;_require(support.get('schema')==HON_UNIT_SUPPORT_SCHEMA and support.get('scope')==scope and support.get('source_material_ref')==scope['material_ref'],'R11_EXACT_HON_UNIT_SOURCE_SCOPE_REQUIRED')

    key=support.get('ex_date');_require(key in scope['exact_ex_dates'] and support.get('ticker')=='HON','R11_EXACT_TWO_HON_EVENTS_REQUIRED')

    m=json.loads(pinned(scope['material_ref']).read_text());rows=[e for e in m['entries'] if e['ticker']=='HON' and e['effective_date']==key];_require(len(rows)==1,'R11_UNIQUE_ORIGINAL_HON_EVENT_REQUIRED');e=rows[0]

    ex=pd.Timestamp(key,tz='America/New_York')+pd.Timedelta(hours=9,minutes=30);u=e['independent_common_cash_USD_share_basis'];prior=e['prior_dated_original_frozen_row'];row=prior['original_frozen_prior_row'];raw=e['prior_and_ex_RAW_metadata']

    _require(pd.Timestamp(e['source_displayed_publication_date'])<pd.Timestamp(key) and pd.Timestamp(e['publicly_available_no_later_than'])<ex and pd.Timestamp(u['accepted_at_utc'])<ex and ex<pd.Timestamp('2026-01-01',tz='America/New_York'),'R11_ORIGINAL_DATE_CAPTURE_AND_UNIT_PREEX_REQUIRED')

    _require(e['actual_first_publication_at'] is None and e['actual_first_publication_timestamp_status']=='UNKNOWN' and e['source_available_at_for_engine'] is None and e['source_engine_availability_role']=='CONSERVATIVE_EXACT_PREEX_ARCHIVE_AVAILABILITY_NOT_FIRST_PUBLICATION_CERTIFICATE' and e['original_literal_rewritten'] is False and e['current_amount_annualized_divided_or_inferred'] is False,'R11_UNKNOWN_FIRST_PUBLICATION_AND_NO_AMOUNT_INFERENCE_REQUIRED')

    _require(row['title_of_class']=='COM' and row['security_id']==row['cusip']=='438516106' and entry['prior_raw_close']['prior_date']==prior['prior_date'] and raw['same_dated_cusip_and_accounting_sid'] is True and raw['ex_identity']==raw['prior_identity']==dict(security_uid='CUSIP:438516106',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.HON') and entry['identity_binding']['issuer']==row['issuer_name'] and entry['identity_binding']['ticker']=='HON' and entry['identity_binding']['listing_identity']=='NASDAQ:HON' and support.get('source_material_event_fingerprint')==_base()._hash(e),'R11_EXACT_ORIGINAL_HON_COMMON_UID_REQUIRED')

    _require(u['common_stock_XBRL_concept']=='us-gaap:CommonStockDividendsPerShareCashPaid' and u['issuer_cik']==773840 and u['exact_current_event_dividend_amount_from_capital_row'] is False and u['current_event_payment_from_financial_paid_row'] is False and e['financial_CommonStockCashPaid_row_not_current_event_amount_or_payment'] is True,'R11_FINANCIAL_ROW_CLASS_UNIT_ONLY_NOT_CURRENT_PAYMENT')

    unit=_original_common_cash_usd_unit(u,pinned,issuer_cik=773840,concept='us-gaap:CommonStockDividendsPerShareCashPaid',class_literal='Cash dividends per share of common stock')

    return _VerifiedHonSupport(profile=scope['profile'],status='PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT',source_common_class_literal='Common Stock',source_CUSIP='438516106',original_frozen_class_literal='COM',no_class_alias=True,original_frozen_class_rewritten=False,source_legal_issuer_literal=row['issuer_name'],source_issuer_field_role='ORIGINAL_FROZEN_ACCOUNTING_ISSUER_LITERAL_NOT_NAME_ALIAS_OR_NEW_LEGAL_IDENTITY',source_listing_identity='NASDAQ:HON',source_US_context_literal='EXPLICIT_SEPARATE_SEC_USD_PER_COMMON_SHARE_UNIT',source_material_event=e,source_material_ref=scope['material_ref'],available_at=None,historical_availability_authority='UNKNOWN',share_quantity_effect=False,USD_unit_original_metadata=unit)



def _hon_announcement_terms(source,binding,projection,pub,capture,full_body):

    _require(isinstance(binding,_VerifiedHonSupport) and full_body is not None,'R11_VALIDATED_HON_SEPARATE_UNIT_BINDING_REQUIRED');e=binding['source_material_event']

    _require(len(source['cash_fragments'])==1,'R11_ONE_UNMODIFIED_COMMON_DECLARATION_REQUIRED');item=source['cash_fragments'][0];text=projection(item)

    _require(text==e['declaration_literal'] and hashlib.sha256(text.encode()).hexdigest()==e['declaration_literal_sha256'] and not re.search(r'\b(?:preferred|ADR|ADS|converted|adjusted|restated)\b',text,re.I),'R11_EXACT_ORIGINAL_HON_DECLARATION_REQUIRED')

    money=re.findall(r'\$(\d+\.\d+)',text);current=e['explicit_current_quarter_amount_literal'];roles=[]

    if e['effective_date']=='2024-11-15':

        m=re.search(r'regular annual cash dividend from \$(\d+\.\d+) to \$(\d+\.\d+) per share\. The increase will be effective starting with the fourth-quarter dividend of \$(\d+\.\d+) per share, which was declared today, and is payable',text)

        _require(m is not None and money==list(m.groups())==['4.32','4.52','1.13'] and Decimal(m.group(3))==Decimal(current),'R11_ALL_ORIGINAL_ANNUAL_COMPARISONS_AND_EXPLICIT_CURRENT_REQUIRED')

        roles=[dict(amount_literal=m.group(1),role='PREVIOUS_REGULAR_ANNUAL_CASH_RATE_NOT_CURRENT_QUARTER_AMOUNT'),dict(amount_literal=m.group(2),role='NEW_REGULAR_ANNUAL_CASH_RATE_NOT_CURRENT_QUARTER_AMOUNT'),dict(amount_literal=m.group(3),role='EXPLICIT_DECLARED_CURRENT_QUARTER_CASH')]

        _require(roles[:2]==e['comparative_amount_roles'],'R11_ORIGINAL_ANNUAL_ROLES_REQUIRED')

    else:

        m=re.search(r"declared a quarterly dividend payment of \$(\d+\.\d+) per share on the Company's common stock\.",text)

        _require(m is not None and money==[m.group(1)] and Decimal(m.group(1))==Decimal(current) and e['comparative_amount_roles']==[],'R11_SINGLE_COMMON_QUARTER_DECLARATION_REQUIRED');roles=[dict(amount_literal=m.group(1),role='EXPLICIT_DECLARED_CURRENT_QUARTER_CASH')]

    dates=r'([A-Za-z]+ \d{1,2}, 20\d{2})';pay=re.search(r'payable on '+dates,text);record=re.search(r'holders of record at the close of business on '+dates,text)

    _require(pay is not None and record is not None and str(pd.Timestamp(pay.group(1)).date())==e['announced_pay_date'] and str(pd.Timestamp(record.group(1)).date())==e['issuer_record_date'],'R11_ORIGINAL_RECORD_AND_PAY_REQUIRED')

    _require(pub==pd.Timestamp(e['source_displayed_publication_date']) and capture==pd.Timestamp(e['publicly_available_no_later_than']),'R11_ORIGINAL_DISPLAYED_DATE_AND_CONSERVATIVE_CAPTURE_REQUIRED')

    return dict(issuer=binding['source_legal_issuer_literal'],ticker='HON',listing='NASDAQ:HON',amount=float(Decimal(current)),record=e['issuer_record_date'],pay=e['announced_pay_date'],publication=str(pub.date()),available=None,currency_basis='EXPLICIT_USD',source_currency_explicit_USD=False,source_currency_separate_SEC_USD_unit=True,body_ref=copy.deepcopy(item['fragment_ref']),header_ref=copy.deepcopy(source['dated_header_observations'][0]['fragment_ref']),source_paragraph=text,source_original_typed_text_digest=hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),source_original_typed_text_digest_recipe='UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT',source_declared_ex_date=None,source_US_context_literal=binding['source_US_context_literal'],original_source_unit_literal='per share',source_subject_role=HON_HTML_TWO_SCOPE['profile'],source_registrant_name_literal=binding['source_legal_issuer_literal'],source_issuer_field_role=binding['source_issuer_field_role'],source_common_cover_class_literal='Common Stock',source_cash_classification_literal='quarterly',source_full_HTTP_sha256=source['received_http_bytes_sha256'],source_full_HTTP_bytes=source['received_bytes'],full_HTTP_body_locally_available=True,current_transport_capture_utc=str(capture.tz_convert('UTC')),capture_is_not_available_at=True,actual_first_publication_at=None,actual_first_publication_authority='UNKNOWN',source_publication_calendar_date_role='ORIGINAL_DISPLAYED_ARTICLE_DATE_NOT_FIRST_PUBLICATION_CERTIFICATE',source_archive_availability_role=e['source_engine_availability_role'],separate_common_cash_unit_available_utc=e['independent_common_cash_USD_share_basis']['accepted_at_utc'],historical_availability_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',actual_SEC_HTTP_or_header_authority=False,source_fragment_physical_sha256=item['fragment_ref']['sha256'],source_text_utf8_sha256=item['visible_text_utf8_sha256'],amount_roles=roles,annual_rate_division_or_inference=False,current_amount_from_capital_statement=False)



CSX_HTML_FOUR_SCOPE = dict(profile='CSX_FOUR_ORIGINAL_ARCHIVE_EXPLICIT_CURRENT_QUARTER_AND_SEPARATE_PREEX_COMMON_USD_UNIT_R12',material_ref=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\CSX_SIX_ORIGINAL_DECLARATION_CLASS_USD_RAW_SOURCE_BINDING_R3.json',sha256='46973ff805d344d24b981702fe43f3c10b4a64f36f253f34e8184667d3ae24fd'),exact_ex_dates=['2024-02-28','2024-08-30','2024-11-29','2025-05-30'],ticker='CSX',issuer_cik=277948,original_CUSIP='126408103',old_source_profiles_unchanged=True,alpha_or_label_expansion=False)

CSX_UNIT_SUPPORT_SCHEMA='CSX_FOUR_SEPARATE_PREEX_SEC_CASH_COMMON_USD_SHARE_UNIT_SUPPORT_R12'

class _VerifiedCsxSupport(dict):pass



def _csx_common_support(payload,entry,support,pinned):

    scope=CSX_HTML_FOUR_SCOPE;_require(support.get('schema')==CSX_UNIT_SUPPORT_SCHEMA and support.get('scope')==scope and support.get('source_material_ref')==scope['material_ref'],'R12_EXACT_CSX_UNIT_SOURCE_SCOPE_REQUIRED')

    key=support.get('ex_date');_require(key in scope['exact_ex_dates'] and support.get('ticker')=='CSX' and support.get('original_CUSIP')=='126408103','R12_EXACT_FOUR_CSX_EVENTS_REQUIRED')

    material=json.loads(pinned(scope['material_ref']).read_text(encoding='utf-8'));matches=[e for e in material['entries'] if e['ticker']=='CSX' and e['effective_date']==key];_require(len(matches)==1,'R12_UNIQUE_ORIGINAL_CSX_EVENT_REQUIRED');e=matches[0]

    projection=json.loads(pinned(e['source_projection_ref']).read_text(encoding='utf-8'));ex=pd.Timestamp(key,tz='America/New_York')+pd.Timedelta(hours=9,minutes=30)

    _require(projection['effective_date']==key and projection['ticker']=='CSX' and projection['literal']==e['source_terms_literal'] and projection['literal_sha256']==hashlib.sha256(e['source_terms_literal'].encode()).hexdigest() and projection['source_displayed_primary_dateline_date']==e['source_primary_dateline_date'] and projection['publicly_available_no_later_than']==e['source_available_no_later_than'],'R12_PINNED_ORIGINAL_CSX_PROJECTION_REQUIRED')

    _require(e['actual_first_publication_at'] is None and projection['actual_first_publication_at'] is None and projection['actual_first_publication_timestamp_status']=='UNKNOWN' and projection['source_availability_role']==e['source_availability_role']=='EXACT_PREEX_ARCHIVE_CAPTURE_CONSERVATIVE_UPPER_BOUND_NOT_FIRST_PUBLICATION_CERTIFICATE','R12_UNKNOWN_FIRST_PUBLICATION_REQUIRED')

    prior=e['frozen_prior_metadata_selection'];row=prior['original_frozen_prior_row'];raw=e['original_two_day_RAW_identity'];_require(row['title_of_class']=='COM' and row['security_id']==row['cusip']=='126408103' and raw['same_dated_cusip_and_accounting_sid'] is True and raw['ex_identity']==raw['prior_identity']==dict(security_uid='CUSIP:126408103',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.CSX') and raw['prior_date']==prior['prior_date']==entry['prior_raw_close']['prior_date'] and entry['identity_binding']['issuer']==row['issuer_name'] and entry['identity_binding']['ticker']=='CSX' and entry['identity_binding']['listing_identity']=='NASDAQ:CSX' and support.get('source_material_event_fingerprint')==_base()._hash(e),'R12_EXACT_ORIGINAL_CSX_COM_UID_REQUIRED')

    proof=json.loads(pinned(e['common_USD_share_source_ref']).read_text(encoding='utf-8'));u=proof['entries'][e['common_USD_share_source_entry_index']]

    _require(u['issuer_cik']==277948 and u['common_stock_XBRL_concept']=='us-gaap:CommonStockDividendsPerShareCashPaid' and u['accepted_header_ref']==e['capital_original_header_ref'] and u['source_document_ref']==e['capital_original_source_document_ref'] and u['capital_fragment_ref']==e['capital_original_bounded_row_ref'] and u['accepted_at_utc']==e['capital_source_accepted_at_utc'] and u['exact_current_event_dividend_amount_from_capital_row'] is False and u['current_event_payment_from_financial_paid_row'] is False and e['capital_unit_usage']=='CLASS_AND_USD_PER_COMMON_SHARE_ONLY_NOT_CURRENT_EVENT_AMOUNT_OR_PAYMENT','R12_ORIGINAL_FINANCIAL_ROW_CLASS_UNIT_ONLY_REQUIRED')

    _require(pd.Timestamp(e['source_primary_dateline_date']).tz_localize('America/New_York')<ex and pd.Timestamp(e['source_available_no_later_than'])<ex and pd.Timestamp(u['accepted_at_utc'])<ex and ex<pd.Timestamp('2026-01-01',tz='America/New_York'),'R12_DATELINE_CAPTURE_AND_UNIT_PREEX_REQUIRED')

    unit=_original_common_cash_usd_unit(u,pinned,issuer_cik=277948,concept='us-gaap:CommonStockDividendsPerShareCashPaid',class_literal='Common Stock Dividends,' if key=='2025-05-30' else 'Common stock dividends,')

    return _VerifiedCsxSupport(profile=scope['profile'],status='PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT',source_common_class_literal='Common Stock',source_CUSIP='126408103',original_frozen_class_literal='COM',no_class_alias=True,original_frozen_class_rewritten=False,source_legal_issuer_literal=row['issuer_name'],source_issuer_field_role='ORIGINAL_FROZEN_ACCOUNTING_ISSUER_LITERAL_NOT_NAME_ALIAS_OR_NEW_LEGAL_IDENTITY',source_listing_identity='NASDAQ:CSX',source_US_context_literal='EXPLICIT_SEPARATE_SEC_USD_PER_COMMON_SHARE_UNIT',source_material_event=e,source_material_ref=scope['material_ref'],available_at=None,historical_availability_authority='UNKNOWN',share_quantity_effect=False,USD_unit_original_metadata=unit)



def _csx_announcement_terms(source,binding,projection,pub,capture,full_body):

    _require(isinstance(binding,_VerifiedCsxSupport) and full_body is not None and len(source['cash_fragments'])==1,'R12_VALIDATED_CSX_UNIT_AND_ONE_ORIGINAL_DECLARATION_REQUIRED');e=binding['source_material_event'];item=source['cash_fragments'][0];text=projection(item)

    _require(text==e['source_terms_literal'] and pub==pd.Timestamp(e['source_primary_dateline_date']) and capture==pd.Timestamp(e['source_available_no_later_than']) and source.get('actual_first_publication_at') is None and source.get('available_at') is None,'R12_EXACT_ORIGINAL_CSX_STATEMENT_AND_UNKNOWN_CLOCK_REQUIRED')

    dates=r'([A-Za-z]+ \d{1,2}, 20\d{2})';prefix=r'JACKSONVILLE, Fla\. – '+dates+r' – CSX Corp\. \(NASDAQ: CSX\) announced that the Company’s Board of Directors approved ';tail=r' on '+dates+r', to shareholders of record at the close of business on '+dates+r'\.'

    money=re.findall(r'\$(\d+\.\d+)',text);roles=[]

    if e['effective_date']=='2024-02-28':

        m=re.fullmatch(prefix+r'a nine percent increase in its quarterly dividend, from \$(\d+\.\d+) to \$(\d+\.\d+) per share\. The new \$(\d+\.\d+) quarterly dividend is payable'+tail,text)

        _require(m is not None and money==list(m.groups()[1:4])==['0.11','0.12','0.12'],'R12_PRIOR_AND_BOTH_EXPLICIT_CURRENT_AMOUNTS_REQUIRED');current=m.group(3);pay=m.group(5);record=m.group(6)

        roles=[dict(amount_literal=m.group(2),role='PRIOR_QUARTER_COMPARISON_NOT_CURRENT_CASH'),dict(amount_literal=current,role='EXPLICIT_APPROVED_CURRENT_QUARTER_CASH'),dict(amount_literal=m.group(4),role='REPEATED_EXPLICIT_CURRENT_QUARTER_CASH_SAME_AMOUNT')]

    else:

        m=re.fullmatch(prefix+r'a \$(\d+\.\d+) per share quarterly dividend on the Company’s common stock\. The dividend is payable'+tail,text)

        _require(m is not None and money==[m.group(2)] and m.group(2)==('0.13' if e['effective_date']=='2025-05-30' else '0.12'),'R12_SINGLE_EXPLICIT_CURRENT_COMMON_QUARTER_AMOUNT_REQUIRED');current=m.group(2);pay=m.group(3);record=m.group(4);roles=[dict(amount_literal=current,role='EXPLICIT_APPROVED_CURRENT_QUARTER_CASH')]

    _require(str(pd.Timestamp(m.group(1)).date())==e['source_primary_dateline_date'] and pay==e['issuer_pay_date_literal'] and record==e['issuer_record_date_literal'],'R12_EXACT_DATELINE_RECORD_AND_PAY_REQUIRED')

    return dict(issuer=binding['source_legal_issuer_literal'],ticker='CSX',listing='NASDAQ:CSX',amount=float(Decimal(current)),record=str(pd.Timestamp(record).date()),pay=str(pd.Timestamp(pay).date()),publication=str(pub.date()),available=None,currency_basis='EXPLICIT_USD',source_currency_explicit_USD=False,source_currency_separate_SEC_USD_unit=True,body_ref=copy.deepcopy(item['fragment_ref']),header_ref=copy.deepcopy(source['dated_header_observations'][0]['fragment_ref']),source_paragraph=text,source_original_typed_text_digest=hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),source_original_typed_text_digest_recipe='UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT',source_declared_ex_date=None,source_US_context_literal=binding['source_US_context_literal'],original_source_unit_literal='per share',source_subject_role=CSX_HTML_FOUR_SCOPE['profile'],source_registrant_name_literal=binding['source_legal_issuer_literal'],source_issuer_field_role=binding['source_issuer_field_role'],source_common_cover_class_literal='Common Stock',source_cash_classification_literal='quarterly',source_full_HTTP_sha256=source['received_http_bytes_sha256'],source_full_HTTP_bytes=source['received_bytes'],full_HTTP_body_locally_available=True,current_transport_capture_utc=str(capture.tz_convert('UTC')),capture_is_not_available_at=True,actual_first_publication_at=None,actual_first_publication_authority='UNKNOWN',source_publication_calendar_date_role='ORIGINAL_DISPLAYED_ARTICLE_DATE_NOT_FIRST_PUBLICATION_CERTIFICATE',source_archive_availability_role=e['source_availability_role'],separate_common_cash_unit_available_utc=e['capital_source_accepted_at_utc'],historical_availability_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',actual_SEC_HTTP_or_header_authority=False,source_fragment_physical_sha256=item['fragment_ref']['sha256'],source_text_utf8_sha256=item['visible_text_utf8_sha256'],amount_roles=roles,annual_rate_division_or_inference=False,percentage_or_prior_amount_calculation=False,original_percentage_literal="nine percent" if e["effective_date"]=="2024-02-28" else None,current_amount_from_capital_statement=False)



class _VerifiedAmatSupport(dict):pass



def _amat_common_support(payload,entry,support,pinned):

    scope=AMAT_HTML_ONE_SCOPE

    _require(support.get('schema')==AMAT_UNIT_SUPPORT_SCHEMA and support.get('scope')==scope and support.get('source_material_ref')==scope['material_ref'] and support.get('ticker')=='AMAT' and support.get('ex_date')=='2025-08-21' and support.get('original_CUSIP')=='038222105','R18_EXACT_AMAT_ONE_UNIT_SCOPE_REQUIRED')

    proof=json.loads(pinned(scope['material_ref']).read_text(encoding='utf-8'));event=proof['event'];identity=proof['frozen_prior_metadata_selection'];row=identity['original_frozen_row'];raw=identity['event'];unit=proof['original_shared_unit_input']

    _require(event==dict(ticker='AMAT',ex_date='2025-08-21',prior_date='2025-08-20',issuer_cik=6951,original_CUSIP='038222105',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.AMAT',record_date='2025-08-21',pay_date='2025-09-11',source_primary_dateline_date='2025-06-10',source_displayed_datetime_literal='Jun 10, 2025 at 4:05 PM EDT',source_available_no_later_than='2025-06-10T21:06:11+00:00',current_amount_literal='0.46'),'R18_EXACT_AMAT_ORIGINAL_EVENT_DATES_REQUIRED')

    _require(row['ticker']=='AMAT' and row['title_of_class']=='COM' and row['cusip']==row['security_id']=='038222105' and row['issuer_name']=='APPLIED MATLS INC' and entry['prior_raw_close']['prior_date']==raw['prior_date']=='2025-08-20' and raw['effective_date']=='2025-08-21' and raw['same_dated_cusip_and_accounting_sid'] is True and raw['ex_identity']==raw['prior_identity']==dict(security_uid='CUSIP:038222105',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.AMAT') and all(entry['identity_binding'].get(k)==v for k,v in dict(issuer=row['issuer_name'],ticker='AMAT',listing_identity='NASDAQ:AMAT').items()),'R18_ORIGINAL_AMAT_COM_CUSIP_AND_DATED_UID_REQUIRED')

    ex=pd.Timestamp('2025-08-21',tz='America/New_York')+pd.Timedelta(hours=9,minutes=30)

    _require(pd.Timestamp(unit['accepted_at_utc'])<pd.Timestamp('2025-06-10',tz='America/New_York') and pd.Timestamp(event['source_available_no_later_than'])<ex and ex<pd.Timestamp('2026-01-01',tz='America/New_York') and proof['actual_first_publication_at'] is None and proof['engine_available_at'] is None and proof['historical_availability_authority']=='UNKNOWN' and proof['source_current_cash_not_inferred_from_prior_policy'] is True and proof['source_cash_not_from_capital_row'] is True and proof['capital_reported_numeric_payload_not_read'] is True and support.get('source_material_event_fingerprint')==_base()._hash(proof),'R18_AMAT_PREEX_UNIT_AND_UNKNOWN_AVAILABILITY_REQUIRED')

    _require(unit['original_capital_row_literal']=='Dividends declared ($','R18_AMAT_ORIGINAL_NONNUMERIC_COMMON_PREFIX_REQUIRED')

    u=_original_common_cash_usd_unit(unit,pinned,issuer_cik=6951,concept='us-gaap:CommonStockDividendsPerShareDeclared',class_literal='Dividends declared')

    prefix=pinned(unit['capital_fragment_ref']).read_bytes();_require(not re.search(rb'>\s*[0-9]',prefix),'R18_NO_REPORTED_CAPITAL_NUMERIC_PAYLOAD_REQUIRED')

    return _VerifiedAmatSupport(profile=scope['profile'],status='PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT',source_common_class_literal='Common Stock',source_CUSIP='038222105',original_frozen_class_literal='COM',no_class_alias=True,original_frozen_class_rewritten=False,source_legal_issuer_literal=row['issuer_name'],source_issuer_field_role='ORIGINAL_FROZEN_ACCOUNTING_ISSUER_LITERAL_NOT_NAME_ALIAS_OR_NEW_LEGAL_IDENTITY',source_listing_identity='NASDAQ:AMAT',source_US_context_literal='EXPLICIT_SEPARATE_SEC_USD_PER_COMMON_SHARE_UNIT',source_material_event=proof,source_material_ref=scope['material_ref'],available_at=None,historical_availability_authority='UNKNOWN',share_quantity_effect=False,USD_unit_original_metadata=u)



def _amat_announcement_terms(source,binding,projection,pub,capture,full_body):

    _require(isinstance(binding,_VerifiedAmatSupport) and full_body is not None and len(source['cash_fragments'])==1,'R18_VERIFIED_AMAT_UNIT_AND_ONE_CURRENT_LITERAL_REQUIRED');proof=binding['source_material_event'];event=proof['event'];item=source['cash_fragments'][0];text=projection(item)

    _require(text==proof['source_terms_literal'] and hashlib.sha256(text.encode()).hexdigest()==proof['source_terms_literal_sha256'] and pub==pd.Timestamp('2025-06-10') and capture==pd.Timestamp(event['source_available_no_later_than']) and source.get('actual_first_publication_at') is None and source.get('available_at') is None,'R18_EXACT_AMAT_CURRENT_LITERAL_AND_UNKNOWN_CLOCK_REQUIRED')

    pattern=r'SANTA CLARA, Calif\. , June 10, 2025 \(GLOBE NEWSWIRE\) -- Applied Materials, Inc\. today announced that its Board of Directors has approved a quarterly cash dividend of \$(0\.46) per share payable on the company’s common stock\. The dividend is payable on (Sept\. 11, 2025) to shareholders of record as of (Aug\. 21, 2025) \.'

    m=re.fullmatch(pattern,text);_require(m is not None and re.findall(r'\$(\d+\.\d+)',text)==['0.46'],'R18_ORIGINAL_APPROVED_AMAT_CURRENT_COMMON_CASH_REQUIRED')

    fragments=proof['archive_selected_source']['original_selected_fragment_proofs'];policy=fragments[2];a,b=policy['original_HTML_byte_range'];_require(0<=a<b<=len(full_body) and full_body[a:b]==_base()._pin(_path_sha_ref(policy['original_fragment_ref'])).read_bytes(),'R18_FULL_ORIGINAL_AMAT_POLICY_BYTES_RETAINED_REQUIRED')

    from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(full_body[a:b].decode());visible=' '.join(' '.join(parser.parts).split())

    roles=[dict(role='PRIOR_QUARTER_POLICY_RATE_NOT_CURRENT_CASH',amount_literal='0.40'),dict(role='POLICY_CURRENT_RATE_CONCORDANCE_NOT_CURRENT_PAYMENT',amount_literal='0.46'),dict(role='NONMONETARY_POLICY_INCREASE_PERCENT',original_literal='15-percent'),dict(role='NONMONETARY_COMPOUND_ANNUAL_GROWTH_CONTEXT',original_literal='15 percent'),dict(role='NONMONETARY_FREE_CASH_FLOW_DISTRIBUTION_CONTEXT',original_literal='90 percent')]

    _require(visible==policy['original_complete_text_projection'] and re.findall(r'\$(\d+\.\d+)',visible)==['0.40','0.46'] and all(x in visible for x in ('15-percent','15 percent','90 percent')) and proof['prior_policy_roles']==roles and proof['current_amount_roles']==[dict(role='EXPLICIT_APPROVED_CURRENT_QUARTER_COMMON_CASH',amount_literal='0.46')],'R18_ALL_ORIGINAL_AMAT_PRIOR_POLICY_AND_PERCENT_ROLES_REQUIRED')

    return dict(issuer=binding['source_legal_issuer_literal'],ticker='AMAT',listing='NASDAQ:AMAT',amount=float(Decimal(m.group(1))),record=str(pd.Timestamp(m.group(3)).date()),pay=str(pd.Timestamp(m.group(2)).date()),publication=str(pub.date()),available=None,currency_basis='EXPLICIT_USD',source_currency_explicit_USD=False,source_currency_separate_SEC_USD_unit=True,body_ref=copy.deepcopy(item['fragment_ref']),header_ref=copy.deepcopy(source['dated_header_observations'][0]['fragment_ref']),source_paragraph=text,source_original_typed_text_digest=hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),source_original_typed_text_digest_recipe='UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT',source_declared_ex_date=None,source_US_context_literal=binding['source_US_context_literal'],original_source_unit_literal='per share',source_subject_role=AMAT_HTML_ONE_SCOPE['profile'],source_registrant_name_literal='Applied Materials, Inc.',source_issuer_field_role=binding['source_issuer_field_role'],source_common_cover_class_literal='Common Stock',source_cash_classification_literal='quarterly',source_full_HTTP_sha256=source['received_http_bytes_sha256'],source_full_HTTP_bytes=source['received_bytes'],full_HTTP_body_locally_available=True,current_transport_capture_utc=str(capture.tz_convert('UTC')),capture_is_not_available_at=True,actual_first_publication_at=None,actual_first_publication_authority='UNKNOWN',source_publication_calendar_date_role='ORIGINAL_DISPLAYED_ARTICLE_DATE_NOT_FIRST_PUBLICATION_CERTIFICATE',source_archive_availability_role='EXACT_PREEX_ARCHIVE_CAPTURE_CONSERVATIVE_UPPER_BOUND_NOT_FIRST_PUBLICATION_CERTIFICATE',separate_common_cash_unit_available_utc=proof['original_shared_unit_input']['accepted_at_utc'],historical_availability_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',actual_SEC_HTTP_or_header_authority=False,source_fragment_physical_sha256=item['fragment_ref']['sha256'],source_text_utf8_sha256=item['visible_text_utf8_sha256'],amount_roles=proof['current_amount_roles']+roles,annual_rate_division_or_inference=False,percentage_or_prior_amount_calculation=False,current_amount_from_capital_statement=False)



def _msft_raw_bridge_allowed(bridge):

    if bridge.get('schema')=='CRM_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R30':
        return bridge.get('scope')==CRM_ONE_SCOPE and bridge.get('ticker')=='CRM' and bridge.get('ex_date')=='2024-07-09' and bridge.get('security_uid')=='CUSIP:79466L302' and bridge.get('accounting_sid')=='FROZEN_RAW_TRANSPORT_CODE:US.CRM' and bridge.get('source_owner_ref')==_ref(__file__)

    if bridge.get('schema')=='V38_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R1':return True

    if bridge.get('schema')=='AMAT_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R18':

        return bridge.get('scope')==AMAT_HTML_ONE_SCOPE and bridge.get('ticker')=='AMAT' and bridge.get('ex_date')=='2025-08-21' and bridge.get('security_uid')=='CUSIP:038222105' and bridge.get('accounting_sid')=='FROZEN_RAW_TRANSPORT_CODE:US.AMAT' and bridge.get('source_owner_ref')==_ref(__file__)

    if bridge.get('schema')=='CSX_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R12':

        return (bridge.get('scope')==CSX_HTML_FOUR_SCOPE and bridge.get('ticker')=='CSX' and bridge.get('ex_date') in CSX_HTML_FOUR_SCOPE['exact_ex_dates'] and bridge.get('security_uid')=='CUSIP:126408103' and bridge.get('accounting_sid')=='FROZEN_RAW_TRANSPORT_CODE:US.CSX' and bridge.get('source_owner_ref')==_ref(__file__))

    if bridge.get('schema')=='HON_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R11':

        return (bridge.get('scope')==HON_HTML_TWO_SCOPE and bridge.get('ticker')=='HON' and bridge.get('ex_date') in HON_HTML_TWO_SCOPE['exact_ex_dates'] and bridge.get('security_uid')=='CUSIP:438516106' and bridge.get('accounting_sid')=='FROZEN_RAW_TRANSPORT_CODE:US.HON' and bridge.get('source_owner_ref')==_ref(__file__))

    return (bridge.get('schema')=='MSFT_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R10'

        and bridge.get('scope')==MSFT_HTML_SIX_SCOPE and bridge.get('ticker')=='MSFT'

        and bridge.get('ex_date') in MSFT_HTML_SIX_SCOPE['exact_ex_dates']

        and bridge.get('security_uid')=='CUSIP:594918104'

        and bridge.get('accounting_sid')=='FROZEN_RAW_TRANSPORT_CODE:US.MSFT'

        and bridge.get('source_owner_ref')==_ref(__file__))



def _msft_native_packet(bundle,bundle_ref):

    base=_base();crm='crm_one_original_declared_common_unit_scope' in bundle;amat='amat_one_original_approved_common_unit_scope' in bundle;csx='csx_four_original_declared_common_unit_scope' in bundle;hon='hon_two_original_declared_common_unit_scope' in bundle;scope=CRM_ONE_SCOPE if crm else AMAT_HTML_ONE_SCOPE if amat else CSX_HTML_FOUR_SCOPE if csx else HON_HTML_TWO_SCOPE if hon else MSFT_HTML_SIX_SCOPE;key='crm_one_original_declared_common_unit_scope' if crm else 'amat_one_original_approved_common_unit_scope' if amat else 'csx_four_original_declared_common_unit_scope' if csx else 'hon_two_original_declared_common_unit_scope' if hon else 'msft_six_original_declared_common_unit_scope';ticker='CRM' if crm else 'AMAT' if amat else 'CSX' if csx else 'HON' if hon else 'MSFT';prefix=ticker;version='R30' if crm else 'R18' if amat else 'R12' if csx else 'R11' if hon else 'R10'

    _require(bundle.get(key)==scope and bundle.get('post_native_dated_raw_cash_namespace_scope')==base.POST_NATIVE_DATED_RAW_CASH_SCOPE and bundle_ref is not None and base._read(bundle_ref)==bundle,'R10_EXACT_PINNED_MSFT_POST_NATIVE_SCOPE_REQUIRED')

    bridge_ref=bundle.get('post_native_dated_raw_cash_namespace_bridge_ref');_require(bridge_ref in bundle['source_refs'],'R10_BRIDGE_PACKET_SOURCE_PIN_REQUIRED');packet=base._read(bridge_ref)

    _require(packet.get('schema')==prefix+'_ORIGINAL_NAMESPACE_TO_EXACT_DATED_RAW_BRIDGE_PACKET_'+version and packet.get('scope')==scope and packet.get('source_owner_ref')==_ref(__file__) and packet.get('current_native_admission') is False and packet.get('strict_PIT') is False,'R10_EXACT_MSFT_BRIDGE_PACKET_REQUIRED')

    proof_ref=packet.get('original_native_proof_ref');_require(proof_ref in bundle['source_refs'],'R10_ORIGINAL_NATIVE_PROOF_PIN_REQUIRED');proof=base._read(proof_ref)

    _require(proof.get('schema')==prefix+('_ONE' if (crm or amat) else '_FOUR' if csx else '_TWO' if hon else '_SIX')+'_ORIGINAL_SOURCE_NAMESPACE_NATIVE_PROOF_'+version and proof.get('status')=='PASS_ORIGINAL_SOURCE_NAMESPACE_PENDING_RAW_PROJECTION' and proof.get('source_owner_ref')==_ref(__file__) and proof.get('strict_PIT') is False and proof.get('fit_or_replay_run') is False and proof.get('source_material_ref')==scope['material_ref'],'R10_ORIGINAL_MSFT_NATIVE_PROOF_REQUIRED')

    prior=proof.get('original_native_bundle_ref');_require(prior in bundle['source_refs'] and packet.get('original_native_bundle_ref')==prior,'R10_ORIGINAL_NATIVE_PRODUCER_CLOSURE_REQUIRED');base._pin(prior)

    bridges=packet['bridges'];_require(bridges and len({(r['original_fact_ref']['path'],r['original_fact_ref']['sha256']) for r in bridges})==len(bridges) and all(_msft_raw_bridge_allowed(r) for r in bridges),'R10_EXACT_UNAMBIGUOUS_MSFT_BRIDGES_REQUIRED')

    _require({r['ex_date'] for r in bridges}=={r['effective_date'] for r in proof['entries']} and all(r['ticker']==ticker and r['effective_date'] in scope['exact_ex_dates'] for r in proof['entries']),'R10_EXACT_ORIGINAL_NATIVE_EVENT_SET_REQUIRED')

    return bridge_ref,proof_ref,bridges,proof['entries']



class _MsftSourceExtend(ast.NodeTransformer):

    def __init__(self,name):self.name=name;self.counts={}

    def visit_If(self,node):

        self.generic_visit(node)

        if self.name=='_original_dated_common_cash_terms' and node.lineno==2941:

            self.counts['article_after_existing_projection_header']=1

            return ast.parse('if isinstance(separate_common_binding,_VerifiedCrmSupport): return _crm_announcement_terms(source,separate_common_binding,projection,pub,capture,full_body)\nif isinstance(separate_common_binding,_VerifiedMsftSupport): return _msft_announcement_terms(source,separate_common_binding,projection,pub,capture,full_body)\nif isinstance(separate_common_binding,_VerifiedHonSupport): return _hon_announcement_terms(source,separate_common_binding,projection,pub,capture,full_body)\nif isinstance(separate_common_binding,_VerifiedCsxSupport): return _csx_announcement_terms(source,separate_common_binding,projection,pub,capture,full_body)\nif isinstance(separate_common_binding,_VerifiedAmatSupport): return _amat_announcement_terms(source,separate_common_binding,projection,pub,capture,full_body)').body+[node]

        if self.name=='_frozen_common_cash_namespace' and node.lineno==3549:

            self.counts['separate_support_after_pinned_load']=1

            old=node.body[1:];old=[ast.If(test=ast.parse("support.get('schema')==AMAT_UNIT_SUPPORT_SCHEMA",mode='eval').body,body=ast.parse('separate_common_binding=_amat_common_support(payload,entry,support,pinned)').body,orelse=old)];node.body=[node.body[0],ast.If(test=ast.parse("support.get('schema')==CRM_UNIT_SUPPORT_SCHEMA",mode='eval').body,body=ast.parse('separate_common_binding=_crm_common_support(payload,entry,support,pinned)').body,orelse=[ast.If(test=ast.parse("support.get('schema')==MSFT_UNIT_SUPPORT_SCHEMA",mode='eval').body,body=ast.parse('separate_common_binding=_msft_common_support(payload,entry,support,pinned)').body,orelse=[ast.If(test=ast.parse("support.get('schema')==HON_UNIT_SUPPORT_SCHEMA",mode='eval').body,body=ast.parse('separate_common_binding=_hon_common_support(payload,entry,support,pinned)').body,orelse=[ast.If(test=ast.parse("support.get('schema')==CSX_UNIT_SUPPORT_SCHEMA",mode='eval').body,body=ast.parse('separate_common_binding=_csx_common_support(payload,entry,support,pinned)').body,orelse=old)])])])]

        if self.name=='bind_source_account_descendant' and node.lineno==3887:

            self.counts['post_native_setup_preserving_old_V38']=1

            original=node.body

            node.body=[ast.If(test=ast.parse("'crm_one_original_declared_common_unit_scope' in bundle or 'msft_six_original_declared_common_unit_scope' in bundle or 'hon_two_original_declared_common_unit_scope' in bundle or 'csx_four_original_declared_common_unit_scope' in bundle or 'amat_one_original_approved_common_unit_scope' in bundle",mode='eval').body,body=ast.parse('bridge_ref,old_proof_ref,post_native_bridges,post_native_proofs=_msft_native_packet(bundle,bundle_ref)').body,orelse=original)]

        return node

    def visit_Compare(self,node):

        self.generic_visit(node)

        if self.name=='_post_native_cash_raw_namespace' and node.lineno==3772 and ast.dump(node.left)==ast.dump(ast.parse("bridge.get('schema')",mode='eval').body):

            self.counts['post_native_schema_only']=1

            return ast.parse('not _msft_raw_bridge_allowed(bridge)',mode='eval').body

        return node



def _owner():

    base=_base();_require(_ref(cash.__file__)['sha256']==CASH_SHA,'R7_CASH_NATIVE_OWNER_CHANGED')

    cash_owner,cash_anchors=_cash_owner()

    ns=dict(vars(base));ns.update(cash=cash_owner,_alphabet_cover_classes=_alphabet_cover_classes,_qsr_source_legal_invalid=_qsr_source_legal_invalid,_qsr_subject_jurisdiction=_qsr_subject_jurisdiction,_ally_original_nyse_matches=_ally_original_nyse_matches,PROFILES=PROFILES,_statement=_statement,_class_binding=_class_binding,_class_allowed=_class_allowed,_subject_class=_subject_class,_binding_fields=_binding_fields,_cns_common_source_role=_cns_common_source_role,_cns_native_static_allowed=_cns_native_static_allowed,_cns_static_entry_allowed=_cns_static_entry_allowed)

    for name,value in tuple(ns.items()):

        if isinstance(value,FunctionType) and value.__globals__ is base.__dict__:

            clone=FunctionType(value.__code__,ns,name,value.__defaults__,value.__closure__);clone.__kwdefaults__=value.__kwdefaults__;ns[name]=clone

    tree=ast.parse(Path(BASE_SOURCE_REF['path']).read_text(encoding='utf-8'));proof={}

    for name,expected in [('_sec_primary_html_cash_terms',dict(profile_eq=2,profile_in=1,subject_class=1,identity_call=1,statement_call=1,binding_fields=1,cns_source_role=1,ally_exact_NYSE_after_original_listing_projection=1,qsr_exact_legal_listing_unit_gate=1,alphabet_exact_original_cover_class=1)),('_existing_frozen_common_identity',dict(frozen_class=1)),('bind_source_account_descendant',dict(cns_native_static=1)),('_sec_frozen_cash_terms',dict(cns_static_entry_dispatch=1,qsr_exact_subject_jurisdiction=1))]:

        node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name));tx=_Extend(name);node=tx.visit(node);ast.fix_missing_locations(node);_require(tx.counts==expected,'R7_BASE_AST_ANCHOR_CHANGED:'+name+':'+str(tx.counts));exec(compile(ast.Module(body=[node],type_ignores=[]),str(Path(__file__)), 'exec'),ns);proof[name]=tx.counts

    ns.update(CRM_UNIT_SUPPORT_SCHEMA=CRM_UNIT_SUPPORT_SCHEMA,_VerifiedCrmSupport=_VerifiedCrmSupport,_crm_common_support=_crm_common_support,_crm_announcement_terms=_crm_announcement_terms,AMAT_UNIT_SUPPORT_SCHEMA=AMAT_UNIT_SUPPORT_SCHEMA,_VerifiedAmatSupport=_VerifiedAmatSupport,_amat_common_support=_amat_common_support,_amat_announcement_terms=_amat_announcement_terms,CSX_UNIT_SUPPORT_SCHEMA=CSX_UNIT_SUPPORT_SCHEMA,_VerifiedCsxSupport=_VerifiedCsxSupport,_csx_common_support=_csx_common_support,_csx_announcement_terms=_csx_announcement_terms,HON_UNIT_SUPPORT_SCHEMA=HON_UNIT_SUPPORT_SCHEMA,_VerifiedHonSupport=_VerifiedHonSupport,_hon_common_support=_hon_common_support,_hon_announcement_terms=_hon_announcement_terms,MSFT_UNIT_SUPPORT_SCHEMA=MSFT_UNIT_SUPPORT_SCHEMA,_VerifiedMsftSupport=_VerifiedMsftSupport,_msft_common_support=_msft_common_support,_msft_announcement_terms=_msft_announcement_terms,_msft_native_packet=_msft_native_packet,_msft_raw_bridge_allowed=_msft_raw_bridge_allowed)

    for name,expected in [('_original_dated_common_cash_terms',dict(article_after_existing_projection_header=1)),('_frozen_common_cash_namespace',dict(separate_support_after_pinned_load=1)),('bind_source_account_descendant',dict(post_native_setup_preserving_old_V38=1)),('_post_native_cash_raw_namespace',dict(post_native_schema_only=1))]:

        # Reparse the already extended binder so the existing R7 CNS opt-in survives.

        if name=='bind_source_account_descendant':

            node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name));node=_Extend(name).visit(node)

        else:node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name))

        tx=_MsftSourceExtend(name);node=tx.visit(node);ast.fix_missing_locations(node);_require(tx.counts==expected,'R10_BASE_AST_ANCHOR_CHANGED:'+name+':'+str(tx.counts));exec(compile(ast.Module(body=[node],type_ignores=[]),str(Path(__file__)),'exec'),ns);proof['msft_'+name]=tx.counts

    # Existing reader may inject a metadata-only predecessor reader in its private source namespace.

    if callable(globals().get('_read')): ns['_read']=globals()['_read']

    proof['cash_adjudicate_post_verified_cash_ex']=cash_anchors

    return SimpleNamespace(**ns),proof



def _sec_frozen_cash_terms(payload,entry,*,source_ref_transport=()):

    owner,_=_owner();return owner._sec_frozen_cash_terms(payload,entry,source_ref_transport=source_ref_transport)



def bind_source_account_descendant(env,original_kwargs,bundle,*,account_dates,bundle_ref=None):

    owner,anchors=_owner()

    _require(bundle.get('source_profile_completion_scope')==SCOPE and bundle_ref is not None and owner._read(bundle_ref)==bundle,'R7_EXACT_PINNED_PROFILE_SCOPE_REQUIRED')

    for r in (BASE_SOURCE_REF,_ref(__file__)):_require(r in bundle['source_refs'],'R7_SOURCE_CLOSURE_REFERENCE_REQUIRED');owner._pin(r)

    result=owner.bind_source_account_descendant(env,original_kwargs,bundle,account_dates=account_dates,bundle_ref=bundle_ref)

    result['receipt']['source_profile_completion_owner']=dict(owner_ref=_ref(__file__),base_ref=BASE_SOURCE_REF,scope=SCOPE,exact_AST_anchors=anchors,old_profiles_unchanged=True)

    return result



QSR_CURRENT_COMMON_LP = 'QSR_EXACT_COMMON_SHARE_EQUAL_LP_QUARTER_CURRENT_SEPARATE_USD_UNIT_R27'
QSR_COMMON_LP_SCOPES = {'QSR|2025-03-21': {'profile': 'QSR_EXACT_COMMON_SHARE_EQUAL_LP_QUARTER_CURRENT_SEPARATE_USD_UNIT_R27', 'ticker': 'QSR', 'ex_date': '2025-03-21', 'prior_date': '2025-03-20', 'issuer_CIK': 1618756, 'original_CUSIP': '76131D103', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.QSR', 'listing_identity': 'NYSE:QSR', 'original_frozen_class_literal': 'COM', 'issuer_jurisdiction': 'CA', 'source_charter_literal': 'Canada', 'source_listing_literal': 'Common Shares, without par value QSR New York Stock Exchange', 'source_registrant_literal': 'RESTAURANT BRANDS INTERNATIONAL INC.', 'record_date': '2025-03-21', 'pay_date': '2025-04-04', 'source_publication_date': '2025-02-12', 'publication_accepted_at_utc': '2025-02-12T11:34:41+00:00', 'source_available_at': '2025-02-21T20:57:46+00:00', 'accession': '0001618756-25-000076', 'original_current_literal': 'The RBI board of directors has declared a dividend of $0.62 per common share and partnership exchangeable unit of RBI LP for the first quarter of 2025. The dividend will be payable on April 4, 2025 to shareholders and unitholders of record at the close of business on March 21, 2025. In connection with the declared dividend, RBI also announced that it is targeting a total of $2.48 in dividends per common share and partnership exchangeable unit of RBI LP for 2025.', 'current_amount_literal': '0.62', 'original_money_tokens': ['0.62', '2.48'], 'original_amount_roles': [{'literal': '0.62', 'role': 'EXPLICIT_CURRENT_QUARTER_COMMON_SHARE_AND_EQUAL_PARTNERSHIP_EXCHANGEABLE_UNIT_AMOUNT'}, {'literal': '2.48', 'role': 'ANNUAL_TARGET_NOT_CURRENT_CASH_NOT_ANNUAL_DIVISION'}], 'original_quarter_literal': 'first quarter of 2025', 'LP_obligation_literal': True, 'current_cash_is_per_common_share': True, 'LP_account_position_created': False, 'annual_amount_divided': False, 'known_future_schedule_only': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\QSR_2025-03-21_EXACT_COMMON_LP_CURRENT_USD_UNIT_SOURCE_ROLE_PROOF_R27_R1.json', 'sha256': '3563664c6d3aea0cacd1b761c6b847d43fe41598fb27040b2dd17b0e435ed359'}}, 'QSR|2025-06-24': {'profile': 'QSR_EXACT_COMMON_SHARE_EQUAL_LP_QUARTER_CURRENT_SEPARATE_USD_UNIT_R27', 'ticker': 'QSR', 'ex_date': '2025-06-24', 'prior_date': '2025-06-23', 'issuer_CIK': 1618756, 'original_CUSIP': '76131D103', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.QSR', 'listing_identity': 'NYSE:QSR', 'original_frozen_class_literal': 'COM', 'issuer_jurisdiction': 'CA', 'source_charter_literal': 'Canada', 'source_listing_literal': 'Common Shares, without par value QSR New York Stock Exchange', 'source_registrant_literal': 'RESTAURANT BRANDS INTERNATIONAL INC.', 'record_date': '2025-06-24', 'pay_date': '2025-07-08', 'source_publication_date': '2025-05-08', 'publication_accepted_at_utc': '2025-05-08T10:32:56+00:00', 'source_available_at': '2025-05-08T20:01:22+00:00', 'accession': '0001618756-25-000238', 'original_current_literal': 'The RBI Board of Directors has declared a dividend of $0.62 per common share and partnership exchangeable unit of RBI LP for the second quarter of 2025. The dividend will be payable on July 8, 2025 to shareholders and unitholders of record at the close of business on June 24, 2025.', 'current_amount_literal': '0.62', 'original_money_tokens': ['0.62'], 'original_amount_roles': [{'literal': '0.62', 'role': 'EXPLICIT_CURRENT_QUARTER_COMMON_SHARE_AND_EQUAL_PARTNERSHIP_EXCHANGEABLE_UNIT_AMOUNT'}], 'original_quarter_literal': 'second quarter of 2025', 'LP_obligation_literal': True, 'current_cash_is_per_common_share': True, 'LP_account_position_created': False, 'annual_amount_divided': False, 'known_future_schedule_only': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\QSR_2025-06-24_EXACT_COMMON_LP_CURRENT_USD_UNIT_SOURCE_ROLE_PROOF_R27_R1.json', 'sha256': '20773837b61a2b742064c35e221d1020588c2f641565b010efe2919b375a5c09'}}, 'QSR|2025-09-23': {'profile': 'QSR_EXACT_COMMON_SHARE_EQUAL_LP_QUARTER_CURRENT_SEPARATE_USD_UNIT_R27', 'ticker': 'QSR', 'ex_date': '2025-09-23', 'prior_date': '2025-09-22', 'issuer_CIK': 1618756, 'original_CUSIP': '76131D103', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.QSR', 'listing_identity': 'NYSE:QSR', 'original_frozen_class_literal': 'COM', 'issuer_jurisdiction': 'CA', 'source_charter_literal': 'Canada', 'source_listing_literal': 'Common Shares, without par value QSR New York Stock Exchange', 'source_registrant_literal': 'RESTAURANT BRANDS INTERNATIONAL INC.', 'record_date': '2025-09-23', 'pay_date': '2025-10-07', 'source_publication_date': '2025-08-07', 'publication_accepted_at_utc': '2025-08-07T10:32:51+00:00', 'source_available_at': '2025-08-07T20:01:37+00:00', 'accession': '0001618756-25-000289', 'original_current_literal': 'The RBI Board of Directors has declared a dividend of $0.62 per common share and partnership exchangeable unit of RBI LP for the third quarter of 2025. The dividend will be payable on October 7, 2025 to shareholders and unitholders of record at the close of business on September 23, 2025.', 'current_amount_literal': '0.62', 'original_money_tokens': ['0.62'], 'original_amount_roles': [{'literal': '0.62', 'role': 'EXPLICIT_CURRENT_QUARTER_COMMON_SHARE_AND_EQUAL_PARTNERSHIP_EXCHANGEABLE_UNIT_AMOUNT'}], 'original_quarter_literal': 'third quarter of 2025', 'LP_obligation_literal': True, 'current_cash_is_per_common_share': True, 'LP_account_position_created': False, 'annual_amount_divided': False, 'known_future_schedule_only': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\QSR_2025-09-23_EXACT_COMMON_LP_CURRENT_USD_UNIT_SOURCE_ROLE_PROOF_R27_R1.json', 'sha256': '356b74cbe92ac0ce217c2be7f991c59ad8ba0f76aea9ea2a24bb329dfd6cd9c9'}}, 'QSR|2025-12-23': {'profile': 'QSR_EXACT_COMMON_SHARE_EQUAL_LP_QUARTER_CURRENT_SEPARATE_USD_UNIT_R27', 'ticker': 'QSR', 'ex_date': '2025-12-23', 'prior_date': '2025-12-22', 'issuer_CIK': 1618756, 'original_CUSIP': '76131D103', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.QSR', 'listing_identity': 'NYSE:QSR', 'original_frozen_class_literal': 'COM', 'issuer_jurisdiction': 'CA', 'source_charter_literal': 'Canada', 'source_listing_literal': 'Common Shares, without par value QSR New York Stock Exchange', 'source_registrant_literal': 'RESTAURANT BRANDS INTERNATIONAL INC.', 'record_date': '2025-12-23', 'pay_date': '2026-01-06', 'source_publication_date': '2025-10-30', 'publication_accepted_at_utc': '2025-10-30T10:35:34+00:00', 'source_available_at': '2025-10-30T20:01:41+00:00', 'accession': '0001618756-25-000297', 'original_current_literal': 'The RBI Board of Directors has declared a dividend of $0.62 per common share and partnership exchangeable unit of RBI LP for the fourth quarter of 2025. The dividend will be payable on January 6, 2026 to shareholders and unitholders of record at the close of business on December 23, 2025.', 'current_amount_literal': '0.62', 'original_money_tokens': ['0.62'], 'original_amount_roles': [{'literal': '0.62', 'role': 'EXPLICIT_CURRENT_QUARTER_COMMON_SHARE_AND_EQUAL_PARTNERSHIP_EXCHANGEABLE_UNIT_AMOUNT'}], 'original_quarter_literal': 'fourth quarter of 2025', 'LP_obligation_literal': True, 'current_cash_is_per_common_share': True, 'LP_account_position_created': False, 'annual_amount_divided': False, 'known_future_schedule_only': True, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\QSR_2025-12-23_EXACT_COMMON_LP_CURRENT_USD_UNIT_SOURCE_ROLE_PROOF_R27_R1.json', 'sha256': 'bcd522ca224298b6c624b0287db20ac8d2b22b52ea1851afafabe0e953eb2756'}}}
QSR_UNIT_CURRENCY_BASIS = 'ORIGINAL_PREEX_SAME_ISSUER_COMMON_USD_DIVIDE_SHARES_UNIT_CURRENT_CASH_LITERAL'


def _qsr_common_lp_scope(facts):
    scope=QSR_COMMON_LP_SCOPES.get(facts.get('ticker','')+'|'+facts.get('exact_frozen_event_key',{}).get('effective_date',''))
    _require(scope is not None and facts.get('sec_filer_cik')==scope['issuer_CIK'] and facts.get('security_id')==scope['accounting_sid'] and facts.get('exact_frozen_event_key',{}).get('ticker')=='QSR','R27_EXACT_QSR_COMMON_LP_TUPLE_REQUIRED')
    return scope


def _qsr_common_lp_semantics(text,facts,publication,*,listed_common_class=None):
    scope=_qsr_common_lp_scope(facts)
    _require(listed_common_class is None and text==scope['original_current_literal'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal(scope['current_amount_literal']) and pd.Timestamp(publication)==pd.Timestamp(scope['source_publication_date']) and re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==scope['original_money_tokens'],'R27_EXACT_ORIGINAL_CURRENT_COMMON_LP_ROLES_REQUIRED')
    _require('per common share and partnership exchangeable unit of RBI LP' in text and scope['original_quarter_literal'] in text and re.search(r'\bpreferred|depositary|special|due.bill|liquidat\w*\b',text,re.I) is None,'R27_ORIGINAL_COMMON_SHARE_QUARTER_AND_SEPARATE_LP_OBLIGATION_REQUIRED')
    return dict(profile=QSR_CURRENT_COMMON_LP,amount_roles=copy.deepcopy(scope['original_amount_roles']),selected_current_amount=scope['current_amount_literal'],record_date=scope['record_date'],pay_date=scope['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['source_role_proof_ref']),quarter_authority=scope['original_quarter_literal'],quarterly_word_inserted=False,current_amount_from_reported_concept=False,current_amount_inferred_from_policy=False,old_amounts_not_discarded=True,annual_amount_created=False,annual_rate_divided_or_inferred=False,original_text_not_rewritten=True,LP_obligation_retained=True,LP_account_position_created=False,known_future_payment_schedule_only=scope['known_future_schedule_only'],actual_2026_payment_or_observation_read=False,source_clock_role='MAX_ACTUAL_CURRENT_AND_PREEX_ORIGINAL_UNIT_ACCEPTANCE_NOT_FIRST_PUBLICATION')


def _qsr_common_lp_support(payload,entry,facts,pinned):
    scope=_qsr_common_lp_scope(facts);base=_base();same=lambda a,b:_path_sha_ref(a)==_path_sha_ref(b)
    _require(payload.get('qsr_exact_current_common_lp_scope')==scope and payload.get('sec_source_transport_profile')==base.SEC_STATIC_SUBMISSION_PROFILE and facts.get('issuer_jurisdiction')=='CA' and facts.get('listing_identity')==scope['listing_identity'] and facts.get('currency')=='USD' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and facts.get('available_at') is None and entry['prior_raw_close']['prior_date']==scope['prior_date'],'R27_EXACT_CANADIAN_COMMON_ORIGINAL_USD_RAW_UNIT_REQUIRED')
    proof=json.loads(pinned(scope['source_role_proof_ref']).read_text(encoding='utf-8'));_require(proof['schema']=='QSR_FOUR_EXACT_COMMON_SHARE_LP_QUARTER_CURRENT_UNIT_SOURCE_PROOF_R27_R1' and proof['event']=={k:v for k,v in scope.items() if k!='source_role_proof_ref'} and proof['actual_first_publication_at'] is None and proof['engine_available_at'] is None and proof['reported_capital_values_used'] is False and proof['actual_2026_observation_or_payment_read'] is False,'R27_PINNED_COMMON_LP_CURRENT_ORIGINAL_UNIT_PROOF_REQUIRED')
    selected=payload['selected_original_cash_fragment'];_qsr_common_lp_semantics(selected['text'],facts,scope['source_publication_date']);source=json.loads(pinned(payload['sec_cash_source_custody_ref']).read_text(encoding='utf-8'));_require(same(source['original_HTTP_ref'],proof['new_actual_main_full_ref']) and same(selected['original_fragment_ref'],proof['current_original_fragment_ref']),'R27_CURRENT_MAIN_AND_LITERAL_REF_REQUIRED')
    capture=json.loads(pinned(_path_sha_ref(proof['new_actual_capture_ref'])).read_text(encoding='utf-8'));_require(capture['response_status']==200 and capture['actual_HTTP_status_observed'] is True and capture['old_HTTP_status_remains_UNKNOWN'] is True and capture['new_HEADER_prefix_equals_old_exactly'] is True and capture['new_SEC_HEADER_equals_old_exactly'] is True and same(capture['original_HTTP_ref'],proof['new_actual_main_full_ref']) and capture['source_accepted_at_utc']==scope['publication_accepted_at_utc'],'R27_NEW_CAPTURE_HEADER_AND_OLD_UNKNOWN_REQUIRED')
    full=pinned(_path_sha_ref(proof['new_actual_main_full_ref']));header=pinned(_path_sha_ref(proof['actual_HEADER_ref'])).read_bytes();stamp=re.search(rb'<ACCEPTANCE-DATETIME>([0-9]{14})',header)[1].decode();accepted=pd.Timestamp(stamp).tz_localize('America/New_York').tz_convert('UTC');_require(scope['accession'].encode() in header and re.search(rb'CENTRAL INDEX KEY:\s*0*1618756\b',header) and accepted==pd.Timestamp(scope['publication_accepted_at_utc']),'R27_ACTUAL_CIK_ACCESSION_ACCEPTANCE_REQUIRED')
    with full.open('rb') as stream:_require(stream.read(65536)==header,'R27_EXACT_FULL_HEADER_BYTES_REQUIRED')
    current=[z for z in proof['physical_original_byte_bindings'] if z['fragment_role']=='cash'];_require(len(current)==1 and selected['original_byte_range']==current[0]['new_full_submission_byte_range'],'R27_CURRENT_ORIGINAL_CASH_PHYSICAL_SCOPE_REQUIRED');z=current[0];a,b=z['new_full_submission_byte_range'];ca,cb=z['old_primary_byte_range'];primary=pinned(_path_sha_ref(proof['original_primary_ref']));_require(0<=ca<cb<=primary.stat().st_size and b-a==cb-ca and b-a<=2048,'R27_CURRENT_BOUNDED_CASH_SOURCE_REQUIRED')
    with full.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)
    with primary.open('rb') as stream:stream.seek(ca);old=stream.read(cb-ca)
    _require(raw==old==pinned(_path_sha_ref(proof['current_original_fragment_ref'])).read_bytes(),'R27_CURRENT_FULL_PRIMARY_FRAGMENT_BYTES_REQUIRED')
    from scripts.storage.refresh_sec_event_originals import FilingText
    parser=FilingText();parser.feed(raw.decode());_require(' '.join(' '.join(parser.parts).split())==scope['original_current_literal'],'R27_ORIGINAL_CURRENT_NATIVE_WORDS_REQUIRED')
    unit=proof['original_unit_helper_input'];_original_common_cash_usd_unit(unit,lambda r:pinned(_path_sha_ref(r)),**proof['original_unit_helper_args']);latest=max(accepted,pd.Timestamp(unit['accepted_at_utc']));_require(latest==pd.Timestamp(scope['source_available_at']) and latest<pd.Timestamp(scope['prior_date'],tz='America/New_York')+pd.Timedelta(hours=16) and latest<pd.Timestamp('2026-01-01',tz='UTC'),'R27_CURRENT_AND_UNIT_MAX_PUBLIC_CLOCK_BEFORE_PRIOR_REQUIRED')
    frozen=base._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer']);_require(frozen is not None,'R27_FROZEN_ORIGINAL_COM_REQUIRED');row=frozen['original_source_row'];dated=base._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned);_require(row['title_of_class']=='COM' and row['ticker']=='QSR' and row['cusip']==row['security_id']==scope['original_CUSIP'] and dated['security_uid']=='CUSIP:'+scope['original_CUSIP'] and dated['accounting_sid']==scope['accounting_sid'] and dated['prior_date']==scope['prior_date'] and dated['ex_date']==scope['ex_date'] and dated['same_dated_UID_and_SID'] is True and dated['share_quantity_effect'] is False,'R27_UNCHANGED_ORIGINAL_CUSIP_SID_AND_DATED_UID_REQUIRED')
    return None


def _qsr_source_legal_invalid(original_invalid,payload,entry,facts,listing,legal_name,US_state,listings,pinned):
    if payload.get('sec_cash_statement_profile')==ALPHABET_CURRENT_ABC:
        scope=_alphabet_abc_scope(facts);_alphabet_abc_support(payload,entry,facts,listing,pinned);_require(US_state=='Delaware' and legal_name==scope['source_registrant_literal'] and listings==[(scope['ticker'],'Nasdaq Stock Market')],'R28_EXACT_ORIGINAL_A_C_LEGAL_VENUE_REQUIRED');return False
    if payload.get('sec_cash_statement_profile')!=QSR_CURRENT_COMMON_LP:return original_invalid
    scope=_qsr_common_lp_scope(facts);_qsr_common_lp_support(payload,entry,facts,pinned)
    _require(listing==scope['source_listing_literal'] and US_state==scope['source_charter_literal'] and legal_name==scope['source_registrant_literal'] and listings==[('QSR','New York Stock Exchange')],'R27_ONLY_ORIGINAL_CANADA_COMMON_SHARE_LEGAL_LISTING_REQUIRED')
    return False


def _qsr_subject_jurisdiction(facts,payload):
    if payload.get('sec_cash_statement_profile')!=QSR_CURRENT_COMMON_LP:return facts.get('issuer_jurisdiction')=='US'
    _qsr_common_lp_scope(facts);return facts.get('issuer_jurisdiction')=='CA'


def _qsr_cash_jurisdiction(facts):
    binding=facts.get('sec_frozen_cash_binding',{})
    if binding.get('sec_cash_statement_profile')!=QSR_CURRENT_COMMON_LP:return facts.get('issuer_jurisdiction')=='US'
    return facts.get('issuer_jurisdiction')=='CA' and _completion_clock(binding,facts)


def _qsr_cash_currency_basis(binding,facts,original_basis):
    if binding.get('sec_cash_statement_profile')==ALPHABET_CURRENT_ABC:_alphabet_abc_scope(facts);return QSR_UNIT_CURRENCY_BASIS
    if binding.get('sec_cash_statement_profile')!=QSR_CURRENT_COMMON_LP:return original_basis
    _qsr_common_lp_scope(facts);return QSR_UNIT_CURRENCY_BASIS

PROFILES = (*PROFILES, QSR_CURRENT_COMMON_LP)
SCOPE = dict(SCOPE, profiles=list(PROFILES))


ALPHABET_CURRENT_ABC = 'ALPHABET_EXACT_ABC_CURRENT_PER_SHARE_CASH_ORIGINAL_SERIES_POLICY_AND_USD_UNIT_R28'
ALPHABET_ABC_SCOPES = {'GOOG|2024-09-09': {'profile': 'ALPHABET_EXACT_ABC_CURRENT_PER_SHARE_CASH_ORIGINAL_SERIES_POLICY_AND_USD_UNIT_R28', 'ticker': 'GOOG', 'ex_date': '2024-09-09', 'prior_date': '2024-09-06', 'issuer_CIK': 1652044, 'original_CUSIP': '02079K107', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.GOOG', 'listing_identity': 'NASDAQ:GOOG', 'original_frozen_class_literal': 'CAP STK CL C', 'listed_common_class': 'C', 'source_charter_literal': 'Delaware', 'source_listing_literal': 'Class C Capital Stock, $0.001 par value GOOG Nasdaq Stock Market LLC', 'source_registrant_literal': 'ALPHABET INC.', 'record_date': '2024-09-09', 'pay_date': '2024-09-16', 'source_publication_date': '2024-07-23', 'publication_accepted_at_utc': '2024-07-23T20:01:54+00:00', 'source_available_at': '2024-07-23T23:12:07+00:00', 'accession': '0001652044-24-000076', 'original_current_literal': 'On July 23, 2024, Alphabet announced a cash dividend of $0.20 per share that will be paid on September 16, 2024, to stockholders of record as of September 9, 2024, on each of the Company’s Class A, Class B, and Class C shares.', 'current_amount_literal': '0.20', 'original_money_tokens': ['0.20'], 'source_action_literal': 'announced', 'policy_classifier_receipt_ref': {'path': 'D:\\us-tech-quant-results\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\ALPHABET_APRIL_CONTIGUOUS_SOURCE_EXCERPT_ORIGINAL_CLASSIFIER_MECHANICAL_RESULT_R4.json', 'sha256': '65d6247a4528f9acdcacaceeb300b7899e70500bad7cb08fd278f337ff464994'}, 'current_clause_quarter_word_present': False, 'current_context_quarter_inferred': False, 'current_currency_tag_in_cash': False, 'other_class_account_position_created': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\GOOG_2024-09-09_EXACT_ABC_CURRENT_UNIT_POLICY_SOURCE_ROLE_PROOF_R28_R1.json', 'sha256': 'ec5724b064d160b3334feb7158c811edf2053b2fdfe65a80947610d8b8ff0a94'}}, 'GOOGL|2024-09-09': {'profile': 'ALPHABET_EXACT_ABC_CURRENT_PER_SHARE_CASH_ORIGINAL_SERIES_POLICY_AND_USD_UNIT_R28', 'ticker': 'GOOGL', 'ex_date': '2024-09-09', 'prior_date': '2024-09-06', 'issuer_CIK': 1652044, 'original_CUSIP': '02079K305', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.GOOGL', 'listing_identity': 'NASDAQ:GOOGL', 'original_frozen_class_literal': 'CAP STK CL A', 'listed_common_class': 'A', 'source_charter_literal': 'Delaware', 'source_listing_literal': 'Class A Common Stock, $0.001 par value GOOGL Nasdaq Stock Market LLC', 'source_registrant_literal': 'ALPHABET INC.', 'record_date': '2024-09-09', 'pay_date': '2024-09-16', 'source_publication_date': '2024-07-23', 'publication_accepted_at_utc': '2024-07-23T20:01:54+00:00', 'source_available_at': '2024-07-23T23:12:07+00:00', 'accession': '0001652044-24-000076', 'original_current_literal': 'On July 23, 2024, Alphabet announced a cash dividend of $0.20 per share that will be paid on September 16, 2024, to stockholders of record as of September 9, 2024, on each of the Company’s Class A, Class B, and Class C shares.', 'current_amount_literal': '0.20', 'original_money_tokens': ['0.20'], 'source_action_literal': 'announced', 'policy_classifier_receipt_ref': {'path': 'D:\\us-tech-quant-results\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\ALPHABET_APRIL_CONTIGUOUS_SOURCE_EXCERPT_ORIGINAL_CLASSIFIER_MECHANICAL_RESULT_R4.json', 'sha256': '65d6247a4528f9acdcacaceeb300b7899e70500bad7cb08fd278f337ff464994'}, 'current_clause_quarter_word_present': False, 'current_context_quarter_inferred': False, 'current_currency_tag_in_cash': False, 'other_class_account_position_created': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\GOOGL_2024-09-09_EXACT_ABC_CURRENT_UNIT_POLICY_SOURCE_ROLE_PROOF_R28_R1.json', 'sha256': 'b11448c481550cd5bab2d90e415ca1b39a5069ef94c7dabdecedc3c3e44d799e'}}, 'GOOG|2025-03-10': {'profile': 'ALPHABET_EXACT_ABC_CURRENT_PER_SHARE_CASH_ORIGINAL_SERIES_POLICY_AND_USD_UNIT_R28', 'ticker': 'GOOG', 'ex_date': '2025-03-10', 'prior_date': '2025-03-07', 'issuer_CIK': 1652044, 'original_CUSIP': '02079K107', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.GOOG', 'listing_identity': 'NASDAQ:GOOG', 'original_frozen_class_literal': 'CAP STK CL C', 'listed_common_class': 'C', 'source_charter_literal': 'Delaware', 'source_listing_literal': 'Class C Capital Stock, $0.001 par value GOOG Nasdaq Stock Market LLC', 'source_registrant_literal': 'ALPHABET INC.', 'record_date': '2025-03-10', 'pay_date': '2025-03-17', 'source_publication_date': '2025-02-04', 'publication_accepted_at_utc': '2025-02-04T21:01:27+00:00', 'source_available_at': '2025-02-05T01:41:40+00:00', 'accession': '0001652044-25-000010', 'original_current_literal': 'On February 4, 2025, Alphabet announced a cash dividend of $0.20 per share that will be paid on March 17, 2025, to stockholders of record as of March 10, 2025, on each of the Company’s Class A, Class B, and Class C shares.', 'current_amount_literal': '0.20', 'original_money_tokens': ['0.20'], 'source_action_literal': 'announced', 'policy_classifier_receipt_ref': {'path': 'D:\\us-tech-quant-results\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\ALPHABET_APRIL_CONTIGUOUS_SOURCE_EXCERPT_ORIGINAL_CLASSIFIER_MECHANICAL_RESULT_R4.json', 'sha256': '65d6247a4528f9acdcacaceeb300b7899e70500bad7cb08fd278f337ff464994'}, 'current_clause_quarter_word_present': False, 'current_context_quarter_inferred': False, 'current_currency_tag_in_cash': False, 'other_class_account_position_created': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\GOOG_2025-03-10_EXACT_ABC_CURRENT_UNIT_POLICY_SOURCE_ROLE_PROOF_R28_R1.json', 'sha256': '09e06b56ab5b974b42600fff735ee54d393491904ce484cec591c3ccfbcb3158'}}, 'GOOGL|2025-03-10': {'profile': 'ALPHABET_EXACT_ABC_CURRENT_PER_SHARE_CASH_ORIGINAL_SERIES_POLICY_AND_USD_UNIT_R28', 'ticker': 'GOOGL', 'ex_date': '2025-03-10', 'prior_date': '2025-03-07', 'issuer_CIK': 1652044, 'original_CUSIP': '02079K305', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.GOOGL', 'listing_identity': 'NASDAQ:GOOGL', 'original_frozen_class_literal': 'CAP STK CL A', 'listed_common_class': 'A', 'source_charter_literal': 'Delaware', 'source_listing_literal': 'Class A Common Stock, $0.001 par value GOOGL Nasdaq Stock Market LLC', 'source_registrant_literal': 'ALPHABET INC.', 'record_date': '2025-03-10', 'pay_date': '2025-03-17', 'source_publication_date': '2025-02-04', 'publication_accepted_at_utc': '2025-02-04T21:01:27+00:00', 'source_available_at': '2025-02-05T01:41:40+00:00', 'accession': '0001652044-25-000010', 'original_current_literal': 'On February 4, 2025, Alphabet announced a cash dividend of $0.20 per share that will be paid on March 17, 2025, to stockholders of record as of March 10, 2025, on each of the Company’s Class A, Class B, and Class C shares.', 'current_amount_literal': '0.20', 'original_money_tokens': ['0.20'], 'source_action_literal': 'announced', 'policy_classifier_receipt_ref': {'path': 'D:\\us-tech-quant-results\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\ALPHABET_APRIL_CONTIGUOUS_SOURCE_EXCERPT_ORIGINAL_CLASSIFIER_MECHANICAL_RESULT_R4.json', 'sha256': '65d6247a4528f9acdcacaceeb300b7899e70500bad7cb08fd278f337ff464994'}, 'current_clause_quarter_word_present': False, 'current_context_quarter_inferred': False, 'current_currency_tag_in_cash': False, 'other_class_account_position_created': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\GOOGL_2025-03-10_EXACT_ABC_CURRENT_UNIT_POLICY_SOURCE_ROLE_PROOF_R28_R1.json', 'sha256': 'fea37035f0a9fc9d6bee90c8e382706ad0893cd7845e8b7271cf2748cb1acb8d'}}, 'GOOG|2024-12-09': {'profile': 'ALPHABET_EXACT_ABC_CURRENT_PER_SHARE_CASH_ORIGINAL_SERIES_POLICY_AND_USD_UNIT_R28', 'ticker': 'GOOG', 'ex_date': '2024-12-09', 'prior_date': '2024-12-06', 'issuer_CIK': 1652044, 'original_CUSIP': '02079K107', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.GOOG', 'listing_identity': 'NASDAQ:GOOG', 'original_frozen_class_literal': 'CAP STK CL C', 'listed_common_class': 'C', 'source_charter_literal': 'Delaware', 'source_listing_literal': 'Class C Capital Stock, $0.001 par value GOOG Nasdaq Stock Market LLC', 'source_registrant_literal': 'Alphabet Inc.', 'record_date': '2024-12-09', 'pay_date': '2024-12-16', 'source_publication_date': '2024-10-29', 'publication_accepted_at_utc': '2024-10-29T23:33:10+00:00', 'source_available_at': '2024-10-29T23:33:10+00:00', 'accession': '0001652044-24-000118', 'original_current_literal': 'On October 29, 2024, Alphabet announced a cash dividend of $0.20 per share that will be paid on December 16, 2024, to stockholders of record as of December 9, 2024, on each of the company’s Class A, Class B, and Class C shares.', 'current_amount_literal': '0.20', 'original_money_tokens': ['0.20'], 'source_action_literal': 'announced', 'policy_classifier_receipt_ref': {'path': 'D:\\us-tech-quant-results\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\ALPHABET_APRIL_CONTIGUOUS_SOURCE_EXCERPT_ORIGINAL_CLASSIFIER_MECHANICAL_RESULT_R4.json', 'sha256': '65d6247a4528f9acdcacaceeb300b7899e70500bad7cb08fd278f337ff464994'}, 'current_clause_quarter_word_present': False, 'current_context_quarter_inferred': False, 'current_currency_tag_in_cash': False, 'other_class_account_position_created': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\GOOG_2024-12-09_EXACT_ABC_CURRENT_UNIT_POLICY_SOURCE_ROLE_PROOF_R28_R1.json', 'sha256': 'dd935a7e966d79ee50cf5abf715dcb32322b2691e5de6bdbb1e1adc40e770a2f'}}, 'GOOGL|2024-12-09': {'profile': 'ALPHABET_EXACT_ABC_CURRENT_PER_SHARE_CASH_ORIGINAL_SERIES_POLICY_AND_USD_UNIT_R28', 'ticker': 'GOOGL', 'ex_date': '2024-12-09', 'prior_date': '2024-12-06', 'issuer_CIK': 1652044, 'original_CUSIP': '02079K305', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.GOOGL', 'listing_identity': 'NASDAQ:GOOGL', 'original_frozen_class_literal': 'CAP STK CL A', 'listed_common_class': 'A', 'source_charter_literal': 'Delaware', 'source_listing_literal': 'Class A Common Stock, $0.001 par value GOOGL Nasdaq Stock Market LLC', 'source_registrant_literal': 'Alphabet Inc.', 'record_date': '2024-12-09', 'pay_date': '2024-12-16', 'source_publication_date': '2024-10-29', 'publication_accepted_at_utc': '2024-10-29T23:33:10+00:00', 'source_available_at': '2024-10-29T23:33:10+00:00', 'accession': '0001652044-24-000118', 'original_current_literal': 'On October 29, 2024, Alphabet announced a cash dividend of $0.20 per share that will be paid on December 16, 2024, to stockholders of record as of December 9, 2024, on each of the company’s Class A, Class B, and Class C shares.', 'current_amount_literal': '0.20', 'original_money_tokens': ['0.20'], 'source_action_literal': 'announced', 'policy_classifier_receipt_ref': {'path': 'D:\\us-tech-quant-results\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\ALPHABET_APRIL_CONTIGUOUS_SOURCE_EXCERPT_ORIGINAL_CLASSIFIER_MECHANICAL_RESULT_R4.json', 'sha256': '65d6247a4528f9acdcacaceeb300b7899e70500bad7cb08fd278f337ff464994'}, 'current_clause_quarter_word_present': False, 'current_context_quarter_inferred': False, 'current_currency_tag_in_cash': False, 'other_class_account_position_created': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\GOOGL_2024-12-09_EXACT_ABC_CURRENT_UNIT_POLICY_SOURCE_ROLE_PROOF_R28_R1.json', 'sha256': '1c37f68602b2ac2c865f40e7bcbd66ffb2bb4a2f7d8f7323813749efc2fa917e'}}, 'GOOGL|2024-06-10': {'profile': 'ALPHABET_EXACT_ABC_CURRENT_PER_SHARE_CASH_ORIGINAL_SERIES_POLICY_AND_USD_UNIT_R28', 'ticker': 'GOOGL', 'ex_date': '2024-06-10', 'prior_date': '2024-06-07', 'issuer_CIK': 1652044, 'original_CUSIP': '02079K305', 'accounting_sid': 'FROZEN_RAW_TRANSPORT_CODE:US.GOOGL', 'listing_identity': 'NASDAQ:GOOGL', 'original_frozen_class_literal': 'CAP STK CL A', 'listed_common_class': 'A', 'source_charter_literal': 'Delaware', 'source_listing_literal': 'Class A Common Stock, $0.001 par value GOOGL Nasdaq Stock Market LLC', 'source_registrant_literal': 'Alphabet Inc.', 'record_date': '2024-06-10', 'pay_date': '2024-06-17', 'source_publication_date': '2024-04-25', 'publication_accepted_at_utc': '2024-04-26T00:22:11+00:00', 'source_available_at': '2024-04-26T00:22:11+00:00', 'accession': '0001652044-24-000053', 'original_current_literal': 'On April 25, 2024, the Board of Directors of Alphabet declared a cash dividend of $ 0.20 per share to be paid on June 17, 2024, to stockholders of record as of June 10, 2024, on each of the company’s Class A, Class B, and Class C shares.', 'current_amount_literal': '0.20', 'original_money_tokens': ['0.20'], 'source_action_literal': 'declared', 'policy_classifier_receipt_ref': {'path': 'D:\\us-tech-quant-results\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\ALPHABET_APRIL_CONTIGUOUS_SOURCE_EXCERPT_ORIGINAL_CLASSIFIER_MECHANICAL_RESULT_R4.json', 'sha256': '65d6247a4528f9acdcacaceeb300b7899e70500bad7cb08fd278f337ff464994'}, 'current_clause_quarter_word_present': False, 'current_context_quarter_inferred': False, 'current_currency_tag_in_cash': True, 'other_class_account_position_created': False, 'source_role_proof_ref': {'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\GOOGL_2024-06-10_EXACT_ABC_CURRENT_UNIT_POLICY_SOURCE_ROLE_PROOF_R28_R1.json', 'sha256': '90f0bac8914148386afe8494d0b41c4f13f1a543114635ba7fd6c50387915b61'}}}


def _alphabet_abc_scope(facts):
    scope=ALPHABET_ABC_SCOPES.get(facts.get('ticker','')+'|'+facts.get('exact_frozen_event_key',{}).get('effective_date',''))
    _require(scope is not None and facts.get('sec_filer_cik')==1652044 and facts.get('security_id')==scope['accounting_sid'] and facts.get('exact_frozen_event_key',{}).get('ticker')==scope['ticker'],'R28_EXACT_ALPHABET_ORIGINAL_A_C_TUPLE_REQUIRED')
    return scope


def _alphabet_abc_semantics(text,facts,publication,*,listed_common_class=None):
    scope=_alphabet_abc_scope(facts)
    _require(listed_common_class==scope['listed_common_class'] and text==scope['original_current_literal'] and facts.get('record_date')==scope['record_date'] and facts.get('pay_date')==scope['pay_date'] and Decimal(str(facts.get('cash_per_raw_share')))==Decimal(scope['current_amount_literal']) and pd.Timestamp(publication)==pd.Timestamp(scope['source_publication_date']) and re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==scope['original_money_tokens'] and 'per share' in text and all('Class '+c in text for c in ('A','B','C')) and scope['source_action_literal'] in text and re.search(r'\bspecial|liquidat\w*|preferred|depositary|due.bill\b',text,re.I) is None,'R28_ORIGINAL_ABC_CURRENT_PER_SHARE_CASH_LITERAL_REQUIRED')
    return dict(profile=ALPHABET_CURRENT_ABC,amount_roles=[dict(role='EXPLICIT_CURRENT_ABC_EQUAL_PER_SHARE_CASH_DECLARED_OR_ANNOUNCED_LITERAL',literal=scope['current_amount_literal'])],selected_current_amount=scope['current_amount_literal'],record_date=scope['record_date'],pay_date=scope['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_proof_ref=copy.deepcopy(scope['source_role_proof_ref']),original_source_action_literal=scope['source_action_literal'],announced_not_rewritten_declared=True,quarterly_word_inserted=False,current_context_quarter_inferred=False,ordinary_source_role='CURRENT_ABC_CASH_AND_ORIGINAL_INITIATED_QUARTERLY_SERIES_POLICY',policy_classifier_receipt_ref=copy.deepcopy(scope['policy_classifier_receipt_ref']),current_amount_from_reported_concept=False,current_amount_from_policy=False,old_amounts_not_discarded=True,annual_amount_created=False,annual_rate_divided_or_inferred=False,original_text_not_rewritten=True,certified_source_cash_share_classes=['A','B','C'],certified_accounting_cash_share_classes=[scope['listed_common_class']],other_class_account_position_created=False,source_clock_role='MAX_CURRENT_UNIT_ORIGINAL_SERIES_POLICY_SEC_ACCEPTANCE_NOT_FIRST_PUBLICATION')


def _alphabet_abc_support(payload,entry,facts,listing,pinned):
    scope=_alphabet_abc_scope(facts);base=_base();same=lambda a,b:_path_sha_ref(a)==_path_sha_ref(b)
    _require(payload.get('alphabet_exact_current_abc_scope')==scope and payload.get('sec_source_transport_profile')==base.SEC_STATIC_PRIMARY_BODY_PROFILE and facts.get('issuer_jurisdiction')=='US' and facts.get('listing_identity')==scope['listing_identity'] and facts.get('currency')=='USD' and facts.get('amount_unit')==cash.USD_PER_RAW_OLD_SHARE and facts.get('quantity_coordinate')==cash.RAW_OLD_SHARE_COORDINATE and facts.get('available_at') is None and entry['prior_raw_close']['prior_date']==scope['prior_date'],'R28_EXACT_SOURCE_ORIGINAL_COMMON_USD_RAW_UNIT_REQUIRED')
    proof=json.loads(pinned(scope['source_role_proof_ref']).read_text(encoding='utf-8'));_require(proof['schema']=='ALPHABET_EXACT_ABC_CURRENT_SHARE_CASH_UNIT_SOURCE_ROLE_PROOF_R28_R1' and proof['event']=={k:v for k,v in scope.items() if k!='source_role_proof_ref'} and proof['original5field']==facts['exact_frozen_event_key'] and proof['actual_first_publication_at'] is None and proof['engine_available_at'] is None and proof['reported_capital_values_used'] is False,'R28_EXACT_ABC_ORIGINAL5FIELD_CURRENT_UNIT_PROOF_REQUIRED')
    selected=payload['selected_original_cash_fragment'];_alphabet_abc_semantics(selected['text'],facts,scope['source_publication_date'],listed_common_class=scope['listed_common_class']);source=json.loads(pinned(payload['sec_cash_source_custody_ref']).read_text(encoding='utf-8'));_require(same(source['original_HTTP_ref'],proof['new_actual_main_full_ref']) and same(selected['original_fragment_ref'],proof['current_original_fragment_ref']),'R28_CURRENT_MAIN_LITERAL_REF_REQUIRED')
    capture=json.loads(pinned(_path_sha_ref(proof['new_actual_capture_ref'])).read_text(encoding='utf-8'));_require(capture['response_status']==200 and capture['actual_HTTP_status_observed'] is True and capture['old_HTTP_status_remains_UNKNOWN'] is True and capture['new_HEADER_prefix_equals_old_exactly'] is True and capture['new_SEC_HEADER_equals_old_exactly'] is True and same(capture['original_HTTP_ref'],proof['new_actual_main_full_ref']) and capture['source_accepted_at_utc']==scope['publication_accepted_at_utc'],'R28_NEW_CURRENT_CAPTURE_ORIGINAL_HEADER_REQUIRED')
    full=pinned(_path_sha_ref(proof['new_actual_main_full_ref']));header=pinned(_path_sha_ref(proof['actual_HEADER_ref'])).read_bytes();stamp=re.search(rb'<ACCEPTANCE-DATETIME>([0-9]{14})',header)[1].decode();accepted=pd.Timestamp(stamp).tz_localize('America/New_York').tz_convert('UTC');_require(scope['accession'].encode() in header and re.search(rb'CENTRAL INDEX KEY:\s*0*1652044\b',header) and accepted==pd.Timestamp(scope['publication_accepted_at_utc']),'R28_ORIGINAL_CIK_ACCESSION_ACCEPTANCE_REQUIRED')
    with full.open('rb') as stream:_require(stream.read(65536)==header,'R28_EXACT_MAIN_HEADER_BYTES_REQUIRED')
    pieces={}
    for role in ('cash','cover_'+scope['listed_common_class'],'charter','registrant'):
        matches=[z for z in proof['physical_original_byte_bindings'] if z['fragment_role']==role];_require(len(matches)==1,'R28_ONE_ORIGINAL_ABC_CURRENT_IDENTITY_FRAGMENT_REQUIRED');z=matches[0];a,b=z['new_full_submission_byte_range'];_require(0<=a<b<=full.stat().st_size and b-a<=8192,'R28_BOUNDED_ORIGINAL_ABC_FRAGMENT_REQUIRED')
        with full.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)
        _require(raw==pinned(_path_sha_ref(z['old_fragment_ref'])).read_bytes(),'R28_EXACT_FULL_FRAGMENT_BYTES_REQUIRED');pieces[role]=raw
        if role=='cash':
            _require(selected['original_byte_range']==[a,b] and same(z['old_fragment_ref'],proof['current_original_fragment_ref']),'R28_EXACT_CURRENT_CASH_PHYSICAL_SPAN_REQUIRED');ca,cb=z['old_primary_byte_range'];primary=pinned(_path_sha_ref(proof['original_primary_ref']))
            with primary.open('rb') as stream:stream.seek(ca);old=stream.read(cb-ca)
            _require(raw==old and cb-ca<=2048,'R28_CURRENT_CASH_PRIMARY_PHYSICAL_BYTES_REQUIRED')
    from scripts.storage.refresh_sec_event_originals import FilingText
    def visible(raw):
        parser=FilingText();parser.feed(raw.decode());return ' '.join(' '.join(parser.parts).split())
    _require(visible(pieces['cash'])==scope['original_current_literal'] and visible(pieces['cover_'+scope['listed_common_class']])==listing==scope['source_listing_literal'] and visible(pieces['charter'])=='Delaware' and visible(pieces['registrant'])==scope['source_registrant_literal'],'R28_ORIGINAL_A_C_LEGAL_LISTING_AND_CURRENT_LITERAL_REQUIRED')
    unit=proof['original_unit_helper_input'];_original_common_cash_usd_unit(unit,lambda r:pinned(_path_sha_ref(r)),**proof['original_unit_helper_args']);policy=json.loads(pinned(_path_sha_ref(scope['policy_classifier_receipt_ref'])).read_text(encoding='utf-8'));_require(policy['classifier_result']['status']=='SOURCE_CLASS_VERIFIED_ORDINARY' and policy['original_classifier_function']=='classify_existing_cash' and policy['current_amount_not_from_policy'] is True and policy['current_wording_not_rewritten'] is True and policy['source_current_context_quarter_inference'] is False,'R28_ORIGINAL_SERIES_POLICY_ORDINARY_MECHANICAL_EVIDENCE_REQUIRED')
    policyprimary=pinned(_path_sha_ref(proof['original_policy_source_primary_ref']));a,b=proof['original_policy_byte_range'];_require(0<=a<b<=policyprimary.stat().st_size and b-a<=2048,'R28_ORIGINAL_CONTIGUOUS_CURRENT_POLICY_BOUNDED_SOURCE_REQUIRED')
    with policyprimary.open('rb') as stream:stream.seek(a);original_policy=stream.read(b-a)
    _require(original_policy==pinned(_path_sha_ref(proof['original_policy_contiguous_fragment_ref'])).read_bytes() and same(proof['original_policy_contiguous_fragment_ref'],policy['contiguous_fragment_ref']) and same(proof['original_policy_source_primary_ref'],policy['source_document_ref']),'R28_ORIGINAL_POLICY_PHYSICAL_EXCERPT_REQUIRED')
    latest=max(accepted,pd.Timestamp(unit['accepted_at_utc']),pd.Timestamp(policy['accepted_at_utc']));_require(latest==pd.Timestamp(scope['source_available_at']) and latest<pd.Timestamp(scope['prior_date'],tz='America/New_York')+pd.Timedelta(hours=16) and latest<pd.Timestamp('2026-01-01',tz='UTC'),'R28_MAX_CURRENT_UNIT_POLICY_BEFORE_PRIOR_CLOCK_REQUIRED')
    frozen=json.loads(pinned(payload['frozen_account_identity_ref']).read_text(encoding='utf-8'));rows=[z['original_source_row'] for z in frozen['rows'] if pd.Timestamp(z['original_source_row']['effective_start'])<=pd.Timestamp(scope['prior_date'])<=pd.Timestamp(z['original_source_row']['effective_end'])];_require(len(rows)==1,'R28_ONE_EXACT_ORIGINAL_A_C_CLASS_INTERVAL_REQUIRED');row=rows[0]
    _require(row['ticker']==scope['ticker'] and row['title_of_class']==scope['original_frozen_class_literal'] and row['cusip']==row['security_id']==scope['original_CUSIP'] and row['security_id_type']=='CUSIP' and listing==scope['source_listing_literal'],'R28_NO_ORIGINAL_CLASS_CUSIP_TICKER_REWRITE_REQUIRED')
    return _VerifiedClass(profile=ALPHABET_CURRENT_ABC,original_frozen_class_literal=row['title_of_class'],original_CUSIP=row['cusip'],ticker=row['ticker'],source_listing_literal=listing,source_legal_issuer_literal=scope['source_registrant_literal'],source_ref=payload['same_file_cash_identity_support_ref'],row_unchanged=True)


def _alphabet_cover_classes(payload,listing,original_classes):
    if payload.get('sec_cash_statement_profile')!=ALPHABET_CURRENT_ABC:return original_classes
    scope=payload.get('alphabet_exact_current_abc_scope',{});_require(scope in ALPHABET_ABC_SCOPES.values() and listing==scope['source_listing_literal'] and re.findall(r'Class ([AC]) (?:Common|Capital) Stock',listing,re.I)==[scope['listed_common_class']],'R28_SINGLE_ORIGINAL_A_C_LISTED_STOCK_CLASS_REQUIRED')
    return {scope['listed_common_class']}

PROFILES = (*PROFILES, ALPHABET_CURRENT_ABC)
CLASS_PROFILES = (*CLASS_PROFILES, ALPHABET_CURRENT_ABC)
SCOPE = dict(SCOPE, profiles=list(PROFILES))


CRM_HLT_MATERIAL_REF = dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\CRM_HLT_TWO_EXACT_CURRENT_COMMON_USD_SOURCE_MATERIAL_R30_R1.json',sha256='4b5ee1433708c7196f2ccf66bf5de8ee45d9673ce5a940e3c6db130c39d91791')
CRM_DECLARED_COMMON_UNIT = 'CRM_EXACT_ARCHIVED_CURRENT_QUARTER_COMMON_NONVALUE_USD_UNIT_R30'
HLT_AUTHORIZED_COMMON_UNIT = 'HLT_EXACT_AUTHORIZED_CURRENT_QUARTER_COMMON_NONVALUE_USD_UNIT_R30'
CRM_ONE_SCOPE = dict(profile=CRM_DECLARED_COMMON_UNIT,material_ref=CRM_HLT_MATERIAL_REF,ticker='CRM',issuer_cik=1108524,original_CUSIP='79466L302',exact_ex_dates=['2024-07-09'])
CRM_UNIT_SUPPORT_SCHEMA = 'CRM_ONE_EXACT_SEPARATE_COMMON_NONVALUE_USD_SHARE_SUPPORT_R30'


def _crm_hlt_source_event(ticker,ex_date,pinned):
    _require((ticker,ex_date) in (('CRM','2024-07-09'),('HLT','2024-02-22')),'R30_EXACT_TWO_CURRENT_SOURCE_EVENTS_REQUIRED')
    material=json.loads(pinned(CRM_HLT_MATERIAL_REF).read_text(encoding='utf-8'))
    _require(material['schema']=='CRM_HLT_TWO_EXACT_CURRENT_COMMON_USD_UNIT_SOURCE_ROLE_MATERIAL_R30' and material['reported_numeric_unit_payload_used'] is False and material['HLT_2023_upper_bound_pay_not_admitted'] is True,'R30_NO_REPORTED_VALUES_OR_UPPER_BOUND_PAYMENT_ADMISSION')
    rows=[z for z in material['events'] if (z['ticker'],z['ex_date'])==(ticker,ex_date)]
    _require(len(rows)==1,'R30_UNIQUE_PINNED_CURRENT_SOURCE_REQUIRED');return rows[0]


def _crm_hlt_unit_source(event,pinned):
    unit=event['unit'];ticker=event['ticker'];cik=1108524 if ticker=='CRM' else 1585689
    _require(event['issuer_cik']==cik and unit['issuer_cik']==cik and unit['common_stock_XBRL_concept']=='us-gaap:CommonStockDividendsPerShareDeclared' and unit['exact_current_event_dividend_amount_from_capital_row'] is False and unit['current_event_payment_from_financial_paid_row'] is False and unit['numeric_CommonStock_value_body_not_read'] is True and event['current_amount_not_from_unit'] is True and event['current_source_literal_rewritten'] is False,'R30_COMMON_CONCEPT_AND_NONVALUE_ONLY_REQUIRED')
    u=_original_common_cash_usd_unit(unit,lambda r:pinned(_path_sha_ref(r)),issuer_cik=cik,concept='us-gaap:CommonStockDividendsPerShareDeclared',class_literal='cash dividend' if ticker=='CRM' else '')
    raw=pinned(_path_sha_ref(unit['capital_fragment_ref'])).read_bytes()
    _require(re.search(rb'<ix:nonFraction\b[^>]*name="us-gaap:CommonStockDividendsPerShareDeclared"[^>]*>\s*$',raw) and not re.search(rb'>\s*[0-9]',raw),'R30_TAG_VALUE_BODY_FORBIDDEN')
    from scripts.storage.refresh_sec_event_originals import FilingText
    fragments=event['independent_common_cover_fragments'];body=pinned(_path_sha_ref(unit['source_document_ref'])) if ticker=='CRM' else pinned(_path_sha_ref(event['source_full_ref']))
    shown={}
    for f in fragments:
        role=f['role'];span=f.get('original_physical_byte_range',f.get('original_byte_range'));r=f.get('original_fragment_ref',f.get('fragment_ref'));a,b=span
        _require(0<=a<b<=body.stat().st_size and b-a<=2048,'R30_BOUNDED_ORIGINAL_NONVALUE_SUPPORT_REQUIRED')
        with body.open('rb') as h:h.seek(a);part=h.read(b-a)
        _require(part==pinned(_path_sha_ref(r)).read_bytes(),'R30_ORIGINAL_NONVALUE_SUPPORT_CHANGED');parser=FilingText();parser.feed(part.decode('utf-8'));shown[role]=' '.join(' '.join(parser.parts).split())
    if ticker=='CRM':
        _require(shown.get('original_CRM_cover_symbol')=='CRM' and shown.get('original_common_cover_class')=='Common Stock, par value $0.001 per share' and shown.get('original_registrant_CIK')=='0001108524' and shown.get('original_registrant_name')=='Salesforce, Inc.','R30_GENERIC_PHRASE_CANNOT_CERTIFY_COMMON_OR_ISSUER')
    else:
        _require(shown.get('COMMON_LISTING_CELL_0')=='Common Stock, $0.01 par value per share' and shown.get('COMMON_LISTING_CELL_1')=='HLT' and shown.get('COMMON_LISTING_CELL_2')=='New York Stock Exchange' and shown.get('REGISTRANT_NAME')=='Hilton Worldwide Holdings Inc.' and shown.get('INCORPORATION')=='Delaware' and event['current_source_explicit_common'] is True,'R30_CURRENT_COMMON_AND_ORIGINAL_HLT_COVER_REQUIRED')
    latest=max(pd.Timestamp(event['source_available_no_later_than']),pd.Timestamp(unit['accepted_at_utc']))
    _require(latest<pd.Timestamp(event['prior_date'],tz='America/New_York')+pd.Timedelta(hours=16) and latest<pd.Timestamp('2026-01-01',tz='UTC') and event['actual_first_publication_at'] is None and event['engine_available_at'] is None,'R30_SOURCE_UNIT_PREPRIOR_AND_UNKNOWN_FIRST_PUBLICATION_REQUIRED')
    return u


class _VerifiedCrmSupport(dict):pass


def _crm_common_support(payload,entry,support,pinned):
    _require(support.get('schema')==CRM_UNIT_SUPPORT_SCHEMA and support.get('scope')==CRM_ONE_SCOPE and support.get('source_material_ref')==CRM_HLT_MATERIAL_REF and support.get('ticker')=='CRM' and support.get('ex_date')=='2024-07-09' and support.get('original_CUSIP')=='79466L302','R30_EXACT_CRM_SUPPORT_SCOPE_REQUIRED')
    event=_crm_hlt_source_event('CRM','2024-07-09',pinned);row=event['identity']['rows'][0]['original_source_row'];u=_crm_hlt_unit_source(event,pinned)
    _require(support.get('source_material_event_fingerprint')==_base()._hash(event) and row['title_of_class']=='COM' and row['security_id']==row['cusip']=='79466L302' and entry['prior_raw_close']['prior_date']=='2024-07-08' and entry['identity_binding']['ticker']=='CRM' and entry['identity_binding']['listing_identity']=='NYSE:CRM' and entry['identity_binding']['issuer']==row['issuer_name'] and event['current_source_explicit_common'] is False,'R30_CURRENT_WORDS_UNCHANGED_AND_FROZEN_CRM_COM_REQUIRED')
    return _VerifiedCrmSupport(profile=CRM_DECLARED_COMMON_UNIT,status='PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT',source_common_class_literal='Common Stock',source_CUSIP='79466L302',original_frozen_class_literal='COM',no_class_alias=True,original_frozen_class_rewritten=False,source_legal_issuer_literal=row['issuer_name'],source_listing_identity='NYSE:CRM',source_US_context_literal='EXPLICIT_SEPARATE_SEC_USD_PER_COMMON_SHARE_UNIT',source_material_event=event,source_material_ref=CRM_HLT_MATERIAL_REF,available_at=None,historical_availability_authority='UNKNOWN',share_quantity_effect=False,USD_unit_original_metadata=u)


def _crm_announcement_terms(source,binding,projection,pub,capture,full_body):
    _require(isinstance(binding,_VerifiedCrmSupport) and full_body is not None and len(source['cash_fragments'])==1,'R30_VERIFIED_CRM_SUPPORT_AND_ORIGINAL_BODY_REQUIRED');e=binding['source_material_event'];item=source['cash_fragments'][0];text=projection(item)
    _require(text==e['source_terms_literal'] and re.fullmatch(r'SAN FRANCISCO--\(BUSINESS WIRE\)-- Salesforce \(NYSE: CRM\), the #1 AI CRM, today announced that its board of directors declared a quarterly cash dividend of \$(0\.40) per share\. The dividend is payable July 25, 2024, to stockholders of record on July 9, 2024\.',text) and re.findall(r'\$(\d+\.\d+)',text)==['0.40'] and 'common' not in text and pub==pd.Timestamp('2024-06-27') and capture==pd.Timestamp('2024-06-28T01:57:03+00:00'),'R30_CURRENT_CRM_LITERAL_AND_REAL_ARCHIVE_BOUND_REQUIRED')
    cap=json.loads(_base()._pin(e['source_capture_ref']).read_text(encoding='utf-8'));a=cap['attempts'][0]
    _require(a['status']=='EXACT_HISTORICAL_PAYLOAD_VALIDATED_BOUNDED_RELEASE_FRAGMENTS' and a['http_status']==200 and a['memento_at_utc']==e['source_available_no_later_than'] and a['source_CDX_route']['original']==source['source_url'] and a['opaque_ref']['sha256']==hashlib.sha256(full_body).hexdigest() and a['actual_CDX_digest']==a['source_CDX_route']['digest'],'R30_ORIGINAL_CRM_ARCHIVE_CAPTURE_REQUIRED')
    return dict(issuer=binding['source_legal_issuer_literal'],ticker='CRM',listing='NYSE:CRM',amount=float(Decimal('0.40')),record=e['record_date'],pay=e['pay_date'],publication=str(pub.date()),available=None,currency_basis='EXPLICIT_USD',source_currency_explicit_USD=False,source_currency_separate_SEC_USD_unit=True,body_ref=copy.deepcopy(item['fragment_ref']),header_ref=copy.deepcopy(source['dated_header_observations'][0]['fragment_ref']),source_paragraph=text,source_original_typed_text_digest=hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),source_original_typed_text_digest_recipe='UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT',source_declared_ex_date=None,source_US_context_literal=binding['source_US_context_literal'],original_source_unit_literal='per share',source_subject_role=CRM_DECLARED_COMMON_UNIT,source_registrant_name_literal='Salesforce, Inc.',source_common_cover_class_literal='Common Stock',source_cash_classification_literal='quarterly',source_full_HTTP_sha256=source['received_http_bytes_sha256'],source_full_HTTP_bytes=source['received_bytes'],full_HTTP_body_locally_available=True,current_transport_capture_utc=str(capture.tz_convert('UTC')),capture_is_not_available_at=True,actual_first_publication_at=None,actual_first_publication_authority='UNKNOWN',separate_common_cash_unit_available_utc=e['unit']['accepted_at_utc'],historical_availability_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',actual_SEC_HTTP_or_header_authority=False,source_fragment_physical_sha256=item['fragment_ref']['sha256'],source_text_utf8_sha256=item['visible_text_utf8_sha256'],current_source_explicit_common=False,current_amount_from_capital_statement=False)


def _hlt_authorized_semantics(text,facts,publication,*,listed_common_class=None):
    e=_crm_hlt_source_event('HLT','2024-02-22',_base()._pin)
    _require(facts.get('ticker')=='HLT' and facts.get('security_id')=='FROZEN_RAW_TRANSPORT_CODE:US.HLT' and facts.get('sec_filer_cik')==1585689 and facts.get('exact_frozen_event_key',{}).get('effective_date')=='2024-02-22' and text==e['source_terms_literal'] and listed_common_class is None and Decimal(str(facts.get('cash_per_raw_share')))==Decimal('0.15') and facts.get('record_date')=='2024-02-23' and facts.get('pay_date')=='2024-03-28' and pd.Timestamp(publication)==pd.Timestamp('2024-02-07') and 'authorized a regular quarterly cash dividend' in text and 'per share of common stock to b e paid on March 28, 2024' in text and 'on or before' not in text,'R30_EXACT_AUTHORIZED_HLT_CURRENT_FIXED_PAY_LITERAL_REQUIRED')
    return dict(profile=HLT_AUTHORIZED_COMMON_UNIT,amount_roles=[dict(role='EXPLICIT_AUTHORIZED_CURRENT_QUARTER_COMMON_CASH',literal='0.15')],selected_current_amount='0.15',record_date='2024-02-23',pay_date='2024-03-28',source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),original_text_not_rewritten=True,original_action_literal='authorized',private_board_date_inferred=False,upper_bound_payment_relabelled_fixed=False,current_amount_from_reported_concept=False,annual_rate_divided_or_inferred=False,source_clock_role='ORIGINAL_SEC_ACCEPTANCE_AND_INDEPENDENT_PREEX_UNIT')


def _hlt_authorized_support(payload,entry,facts,pinned):
    e=_crm_hlt_source_event('HLT','2024-02-22',pinned);_crm_hlt_unit_source(e,pinned)
    _require(payload.get('crm_hlt_exact_source_material_ref')==CRM_HLT_MATERIAL_REF and payload.get('sec_source_transport_profile')==_base().SEC_STATIC_SUBMISSION_PROFILE and facts.get('listing_identity')=='NYSE:HLT' and entry['prior_raw_close']['prior_date']=='2024-02-21','R30_EXACT_STATIC_HLT_SOURCE_AND_PRIOR_REQUIRED')
    _hlt_authorized_semantics(payload['selected_original_cash_fragment']['text'],facts,'2024-02-07')
    frozen=_base()._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer']);_require(frozen is not None and frozen['original_source_row']['title_of_class']=='COM' and frozen['original_source_row']['cusip']=='43300A203','R30_ORIGINAL_HLT_COM_CUSIP_REQUIRED')
    dated=_base()._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned);_require(dated['security_uid']=='CUSIP:43300A203' and dated['accounting_sid']=='FROZEN_RAW_TRANSPORT_CODE:US.HLT' and dated['same_dated_UID_and_SID'] is True,'R30_ORIGINAL_HLT_DATED_UID_REQUIRED');return None


PROFILES = (*PROFILES, HLT_AUTHORIZED_COMMON_UNIT)
