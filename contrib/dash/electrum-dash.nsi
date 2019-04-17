;--------------------------------
;Include Modern UI
  !include "TextFunc.nsh" ;Needed for the $GetSize function. I know, doesn't sound logical, it isn't.
  !include "MUI2.nsh"
  !include "x64.nsh"
  
;--------------------------------
;Variables

  !define PRODUCT_NAME "Dash Electrum"
  !define PRODUCT_NAME_NO_SPACE "Dash-Electrum"
  !define PREV_PROD_NAME "Electrum-DASH"
  !define PREV_PROD_NAME2 "Dash-Electrum"
  !define PRODUCT_WEB_SITE "https://github.com/akhavr/electrum-dash"
  !define PRODUCT_PUBLISHER "Electrum Technologies GmbH"
  !define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
  !define PREV_PROD_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PREV_PROD_NAME}"
  !define PREV_PROD_UNINST_KEY2 "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PREV_PROD_NAME2}"
  !define BUILD_ARCH "${WINEARCH}"

  Var PREVINSTDIR
;--------------------------------
;General

  ;Name and file
  Name "${PRODUCT_NAME}"
  OutFile "dist/${PRODUCT_NAME_NO_SPACE}-${PRODUCT_VERSION}-setup-${BUILD_ARCH}.exe"

  ;Default installation folder
  InstallDir "$PROGRAMFILES\${PRODUCT_NAME}"

  ;Get installation folder from registry if available
  InstallDirRegKey HKCU "Software\${PRODUCT_NAME}" ""

  ;Request application privileges for Windows Vista
  RequestExecutionLevel admin

  ;Specifies whether or not the installer will perform a CRC on itself before allowing an install
  CRCCheck on
  
  ;Sets whether or not the details of the install are shown. Can be 'hide' (the default) to hide the details by default, allowing the user to view them, or 'show' to show them by default, or 'nevershow', to prevent the user from ever seeing them.
  ShowInstDetails show
  
  ;Sets whether or not the details of the uninstall  are shown. Can be 'hide' (the default) to hide the details by default, allowing the user to view them, or 'show' to show them by default, or 'nevershow', to prevent the user from ever seeing them.
  ShowUninstDetails show
  
  ;Sets the colors to use for the install info screen (the default is 00FF00 000000. Use the form RRGGBB (in hexadecimal, as in HTML, only minus the leading '#', since # can be used for comments). Note that if "/windows" is specified as the only parameter, the default windows colors will be used.
  InstallColors /windows
  
  ;This command sets the compression algorithm used to compress files/data in the installer. (http://nsis.sourceforge.net/Reference/SetCompressor)
  SetCompressor /SOLID lzma
  
  ;Sets the dictionary size in megabytes (MB) used by the LZMA compressor (default is 8 MB).
  SetCompressorDictSize 64
  
  ;Sets the text that is shown (by default it is 'Nullsoft Install System vX.XX') in the bottom of the install window. Setting this to an empty string ("") uses the default; to set the string to blank, use " " (a space).
  BrandingText "${PRODUCT_NAME} Installer v${PRODUCT_VERSION}"
  
  ;Sets what the titlebars of the installer will display. By default, it is 'Name Setup', where Name is specified with the Name command. You can, however, override it with 'MyApp Installer' or whatever. If you specify an empty string (""), the default will be used (you can however specify " " to achieve a blank string)
  Caption "${PRODUCT_NAME}"

  ;Adds the Product Version on top of the Version Tab in the Properties of the file.
  VIProductVersion 1.0.0.0
  
  ;VIAddVersionKey - Adds a field in the Version Tab of the File Properties. This can either be a field provided by the system or a user defined field.
  VIAddVersionKey ProductName "${PRODUCT_NAME} Installer"
  VIAddVersionKey Comments "The installer for ${PRODUCT_NAME}"
  VIAddVersionKey CompanyName "${PRODUCT_NAME}"
  VIAddVersionKey LegalCopyright "2013-2018 ${PRODUCT_PUBLISHER}"
  VIAddVersionKey FileDescription "${PRODUCT_NAME} Installer"
  VIAddVersionKey FileVersion ${PRODUCT_VERSION}
  VIAddVersionKey ProductVersion ${PRODUCT_VERSION}
  VIAddVersionKey InternalName "${PRODUCT_NAME} Installer"
  VIAddVersionKey LegalTrademarks "${PRODUCT_NAME} is a trademark of ${PRODUCT_PUBLISHER}" 
  VIAddVersionKey OriginalFilename "${PRODUCT_NAME}-${PRODUCT_VERSION}-setup-${BUILD_ARCH}.exe"

;--------------------------------
;Interface Settings

  !define MUI_ABORTWARNING
  !define MUI_ABORTWARNING_TEXT "Are you sure you wish to abort the installation of ${PRODUCT_NAME}?"
  
  !define MUI_ICON "electrum_dash\gui\icons\electrum-dash.ico"
  
;--------------------------------
;Pages

  !insertmacro MUI_PAGE_DIRECTORY
  !insertmacro MUI_PAGE_COMPONENTS
  !insertmacro MUI_PAGE_INSTFILES
  !insertmacro MUI_UNPAGE_CONFIRM
  !insertmacro MUI_UNPAGE_INSTFILES

;--------------------------------
;Languages

  !insertmacro MUI_LANGUAGE "English"

;--------------------------------
;Installer Sections

;Check if we have Administrator rights
Function .onInit
	UserInfo::GetAccountType
	pop $0
	${If} $0 != "admin" ;Require admin rights on NT4+
		MessageBox mb_iconstop "Administrator rights required!"
		SetErrorLevel 740 ;ERROR_ELEVATION_REQUIRED
		Quit
	${EndIf}

    ${If} ${RunningX64}
        SetRegView 64
        StrCpy $INSTDIR "$PROGRAMFILES64\${PRODUCT_NAME}"
    ${Else}
        ${If} ${BUILD_ARCH} == "win64"
            MessageBox MB_OK|MB_ICONSTOP "Can not Install 64-bit App On 32-bit OS!"
            Abort
        ${EndIf}
    ${EndIf}
FunctionEnd

Section "${PRODUCT_NAME}" SectionDE
  SetOutPath $INSTDIR

  ;Uninstall prev product name versions
  ReadRegStr $PREVINSTDIR HKCU "Software\${PREV_PROD_NAME}" ""
  ${If} ${PREVINSTDIR} != ""
    RMDir /r "$PREVINSTDIR\*.*"
    RMDir "$PREVINSTDIR"

    Delete "$DESKTOP\${PREV_PROD_NAME}.lnk"
    Delete "$SMPROGRAMS\${PREV_PROD_NAME}\*.*"
    RMDir  "$SMPROGRAMS\${PREV_PROD_NAME}"

    DeleteRegKey HKCU "Software\Classes\dash"
    DeleteRegKey HKCU "Software\${PREV_PROD_NAME}"
    DeleteRegKey HKCU "${PREV_PROD_UNINST_KEY}"
  ${EndIf}

  ;Uninstall prev2 product name versions
  ReadRegStr $PREVINSTDIR HKCU "Software\${PREV_PROD_NAME2}" ""
  ${If} ${PREVINSTDIR} != ""
    RMDir /r "$PREVINSTDIR\*.*"
    RMDir "$PREVINSTDIR"

    Delete "$DESKTOP\${PREV_PROD_NAME2}.lnk"
    Delete "$SMPROGRAMS\${PREV_PROD_NAME2}\*.*"
    RMDir  "$SMPROGRAMS\${PREV_PROD_NAME2}"

    DeleteRegKey HKCU "Software\Classes\dash"
    DeleteRegKey HKCU "Software\${PREV_PROD_NAME2}"
    DeleteRegKey HKCU "${PREV_PROD_UNINST_KEY2}"
  ${EndIf}

  ;Uninstall previous version files
  RMDir /r "$INSTDIR\*.*"
  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\*.*"

  ;Files to pack into the installer
  File /r "dist\electrum-dash\*.*"
  File "electrum_dash\gui\icons\electrum-dash.ico"

  ;Store installation folder
  WriteRegStr HKCU "Software\${PRODUCT_NAME}" "" $INSTDIR

  ;Create uninstaller
  DetailPrint "Creating uninstaller..."
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ;Create desktop shortcut
  DetailPrint "Creating desktop shortcut..."
  CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\electrum-dash-${PRODUCT_VERSION}.exe" ""

  ;Create start-menu items
  DetailPrint "Creating start-menu items..."
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\Uninstall.exe" 0
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\electrum-dash-${PRODUCT_VERSION}.exe" "" "$INSTDIR\electrum-dash-${PRODUCT_VERSION}.exe" 0
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME} Testnet.lnk" "$INSTDIR\electrum-dash-${PRODUCT_VERSION}.exe" "--testnet" "$INSTDIR\electrum-dash-${PRODUCT_VERSION}.exe" 0


  ;Links dash: URI's to Electrum
  WriteRegStr HKCU "Software\Classes\dash" "" "URL:dash Protocol"
  WriteRegStr HKCU "Software\Classes\dash" "URL Protocol" ""
  WriteRegStr HKCU "Software\Classes\dash" "DefaultIcon" "$\"$INSTDIR\electrum-dash.ico, 0$\""
  WriteRegStr HKCU "Software\Classes\dash\shell\open\command" "" "$\"$INSTDIR\electrum-dash-${PRODUCT_VERSION}.exe$\" $\"%1$\""

  ;Adds an uninstaller possibility to Windows Uninstall or change a program section
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayName" "$(^Name)"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\electrum-dash.ico"

  ;Fixes Windows broken size estimates
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${PRODUCT_UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "Tor Proxy" SectionTor
  GetTempFileName $0
  File /oname=$0 "dist\tor-proxy-setup.exe"
  ExecWait "$0"
  Delete "$0"
SectionEnd

;--------------------------------
;Descriptions
LangString DESC_DE ${LANG_ENGLISH} "Dash Electrum Wallet"
LangString DESC_TOR ${LANG_ENGLISH} "The Tor Project Socks Proxy"

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
!insertmacro MUI_DESCRIPTION_TEXT ${SectionDE} $(DESC_DE)
!insertmacro MUI_DESCRIPTION_TEXT ${SectionTor} $(DESC_TOR)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

;--------------------------------
;Uninstaller Section

Section "Uninstall"
  RMDir /r "$INSTDIR\*.*"

  RMDir "$INSTDIR"

  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\*.*"
  RMDir  "$SMPROGRAMS\${PRODUCT_NAME}"
  
  DeleteRegKey HKCU "Software\Classes\dash"
  DeleteRegKey HKCU "Software\${PRODUCT_NAME}"
  DeleteRegKey HKCU "${PRODUCT_UNINST_KEY}"
SectionEnd
