from app.openrent.listings import _is_bot_page


AWS_WAF_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <title>Human Verification</title>
    <script type="text/javascript">
    window.awsWafCookieDomainList = [];
    window.gokuProps = {"key":"AQID","iv":"CgAH","context":"YiwM"};
    </script>
</head>
<body>
    <div id="captcha-container"></div>
    <script type="text/javascript">
        AwsWafIntegration.saveReferrer();
        CaptchaScript.renderCaptcha(document.querySelector("#captcha-container"));
    </script>
    <noscript>verify that you're not a robot by solving a CAPTCHA puzzle.</noscript>
</body>
</html>"""

NORMAL_SEARCH_PAGE = """<html><head>
<title>Properties to Rent in Lewisham, London from Private Landlords</title>
<script src="https://www.google.com/recaptcha/api.js"></script>
</head><body>
<div class="g-recaptcha"></div>
<a href="/2884260">2 bed flat</a>
</body></html>"""


def test_aws_waf_captcha_page_is_bot_wall():
    assert _is_bot_page(AWS_WAF_PAGE, "Human Verification") == "AWS WAF CAPTCHA"


def test_aws_waf_detected_from_markup_even_without_title():
    assert _is_bot_page(AWS_WAF_PAGE, "") == "AWS WAF CAPTCHA"


def test_normal_search_page_with_recaptcha_widget_is_not_bot_wall():
    title = "Properties to Rent in Lewisham, London from Private Landlords"
    assert _is_bot_page(NORMAL_SEARCH_PAGE, title) is None


def test_captcha_container_alone_is_not_enough():
    html = '<html><body><div id="captcha-container"></div></body></html>'
    assert _is_bot_page(html, "My Enquiries | OpenRent") is None
