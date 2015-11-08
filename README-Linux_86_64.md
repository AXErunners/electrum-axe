### Electrum-DASH - lightweight multi-coin client
Electrum-DASH provides a basic SPV wallet for Dashpay. It is a BIP-0044-compliant wallet based on the original Electrum for Bitcoin. This Electrum-DASH client uses Electrum servers to retrieve necessary blockchain headaer & transaction data, so no "Electrum-DASH server" is necessary.

Because of the Simplified Payment Verification nature of the wallet, services requiring Masternode communications, such as DarkSend and InstantX are not available.

Homepage: https://dashpay.io/electrum-DASH




1. ELECTRUM_DASH ON LINUX
----------------------

 - Installer package is provided at https://dashpay.io/electrum-DASH
 - To download and use:
    ```
    cd ~
    wget https://dashpay.io/electrum-DASH/releases/v2.4.1/Electrum-DASH-2.4.1-Linux_x86_64.tgz
    tar -xpzvf Electrum-DASH-2.4.1-Linux_x86_64.tgz
    cd Electrum-DASH-2.4.1
    ./electrum-DASH_x86_64.bin
    ```


Once successfully installed simply type
   ```
   electrum-DASH
   ```
   Your wallets will be located in /home/YOUR_LOGIN_NAME/.electrum-DASH/wallets

Installation on 32bit machines is best achieved via github master or TAGGED branches

2. HOW OFFICIAL PACKAGES ARE CREATED
------------------------------------

See contrib/electrum-DASH-release/README.md for complete details on mazaclub release process

