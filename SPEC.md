I would like to implement a new online service where user can add a pruduct by name. the service should automatically observe online offers of the product in predefined online shops and notify if there is any discount detected.

Composition
- top level product list e.g. laptop Zenbook duo, Haier Couture Care 11
- for each procudt list of exact models, eg. UX8407AA-SN515X ,  UX8407AA-SN129X (sometimes product has only one model e.g. Haier Couture Care 11 CLC108-GNU1-S)
- for each model a list of offers (urls) to be observed

Typical Flow
1. user adds a new product to be observed
2. service founds all models of the product (eg using gemini - propose something). finds shop that have all the models and give links to offers
3. user chooses which models he wants to observe
4. for each model service finds offers on predefined shops (listed bellow) and lists  the offers (urls) per model
5. per model user manually chooses which offers should be observed
6. user can manualy add offers to observation list
7. after list is submites user starts observing
8. service remembers every price fetched 
9. whenerever product price goes down servcie sends email

Addtionally:
- Service sends summary emails every x hours with current lowest price for each observed product with link to best offer currently
- the service needs to be able to go around anti scraper programs. Give some possible approaches. (probably there are things that we cannot go around like turnstiles captcha. in this case it need to colect cases of unsecceful checks and alert in a summary email these cases every X hours).
- it shoud be easy to extend  with new shops to the list
  

Configuration
- frequency of offers check
- frequency of summary emails
- email to send to

Views 
- CRUD for creating observarors
- summary for the products (current lowest price. price change hisotry)

Shops
Urls for Zenbook duo UX8407AA-SN515X. Some exaples does not have UX8407AA-SN515X, so it falled back to other models
Find how to parse offer of each of these shops.
Most of shops have one ofer per product, but there are 2 special cases:
ceneo - it aggregaes offers from multiple shops. service needs to checkout the cheepest offer for model
allegro - multiple offers. service needs to on every iteration find the chipest offer and make sure that the model is correct.
E.g. when observing UX8407AA-SN515X
This is good: https://allegro.pl/produkt/laptop-asus-zenbook-duo-14-intel-ultra-x9-32-gb-1-tb-w11p-ea537f82-3ea8-41c2-938d-e532122b7881?offerId=19025346649
This is not: https://allegro.pl/produkt/laptop-asus-zenbook-duo-14-144hz-ultra-7-355-32gb-ram-1tb-ssd-windows-11p-4f0f0d69-58fc-4dd9-b70d-320994eb2c26?offerId=19061532037

Primary Match: Exact UX8407AA-SN515X (Ultra X9 378H / 32GB / 1TB / W11P)
ASUS Store Polska: https://estore.asus.com/pl/90nb16v1-m00uw0-asus-zenbook-duo-ux8407-copilot-pc.html

x-kom.pl: https://www.x-kom.pl/p/1610557-laptop-14-asus-zenbook-duo-ultra-x9-378h-32gb-1tb-win11p-oled.html

Komputronik.pl: https://www.komputronik.pl/product/1016402/laptop-asus-zenbook-duo-oled-ux8407aa-sn515x-ultra-x9-378h-14-3k-144hz-dotyk-32gb-1tb-w11p.html

RTV EURO AGD: https://www.euro.com.pl/laptopy-i-netbooki/asus-laptop-asus-zd-14-32-1-w11p-touch.bhtml

Media Expert: https://www.mediaexpert.pl/komputery-i-tablety/laptopy-i-ultrabooki/laptopy/laptop-asus-zenbook-duo-ux8407aa-sn515x-14-oled-144hz-ultra-x9-378h-32gb-ram-1tb-ssd-windows-11-professional-funkcje-ai

Neonet: https://www.neonet.pl/p/1610557-laptop-asus-zenbook-duo-ultra-x9-378h-32gb-1tb-win11p-oled.html

Deluxury.pl: https://deluxury.pl/pl/p/Laptop-Asus-ZenBook-Duo-OLED-UX8407AA-SN515X-Ultra-X9-378H-32GB-1TB-W11P/41974

TechLord.pl: https://techlord.pl/asus-zenbook-duo-ux8407aa-ultra-x9-378h32gb1tbw11p-oled-144hz-dotyk-p-39087.html

Allegro.pl: https://allegro.pl/produkt/laptop-asus-zenbook-duo-oled-ux8407aa-sn515x-ultra-x9-378h-32gb-1tb-w11p-ea537f82-3ea8-41c2-938d-e532122b7881?offerId=18824244324

Empik.com: https://www.empik.com/asus-zenbook-duo-oled-ux8407aa-sn515x-ultra-x9-378h-14-3k-144hz-dotyk-32gb-1tb-w11p-asus,p1778781306,elektronika-p

Ceneo.pl (Price Comparison for SN515X): https://www.ceneo.pl/199125559

Fallback 1: Other Current Zenbook Duo Models (UX8407AA)
Morele.net (UX8407AA-SN129X): https://www.morele.net/laptop-asus-zenbook-duo-oled-ux8407-ultra-7-355-32-gb-1-tb-w11-pro-144-hz-ux8407aa-sn129x-16224566/

OleOle.pl (UX8407AA-SN169X): https://www.oleole.pl/laptopy-i-netbooki/asus-laptop-asus-zd-14-ux9-32-1-w11p.bhtml

Electro.pl (UX8407AA-SN129X): https://www.electro.pl/komputery-i-tablety/laptopy-i-ultrabooki/laptopy/laptop-asus-zenbook-duo-ux8407aa-sn129x-14-oled-144hz-ultra-7-355-32gb-ram-1tb-ssd-windows-11-professional-funkcje-ai

Avans.pl (UX8407AA-SN129X): https://www.avans.pl/komputery-i-tablety/laptopy-i-ultrabooki/laptopy/laptop-asus-zenbook-duo-ux8407aa-sn129x-14-oled-144hz-ultra-7-355-32gb-ram-1tb-ssd-windows-11-professional-funkcje-ai

Fallback 2: Current Single-Screen Zenbook Models
Media Markt (Zenbook 14 UM3406GA): https://mediamarkt.pl/pl/product/_laptop-asus-zenbook-14-um3406ga-qd013w-wuxga-oled-amd-ryzentmai-5-430-16-gb-ram-512-gb-ssd-radeontm-windows-11-home-czarny-jade-black-1502711.html

Questions:
- technology
- how to bypass antiscraping protections


