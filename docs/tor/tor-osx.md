# macOS Tor Proxy setup

To install Tor Proxy on macOS using [homebrew](https://brew.sh/)
package manager first install homebrew:

```
export BREW_GITHUB_URL="https://raw.githubusercontent.com/Homebrew/"
export BREW_INSTALL_URL="${BREW_GITHUB_URL}install/master/install"
/usr/bin/ruby -e "$(curl -fsSL ${BREW_INSTALL_URL})"
```

Then install Tor Proxy:

```
brew install tor

brew services start tor
```
