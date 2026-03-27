class Gw < Formula
  include Language::Python::Virtualenv

  desc "Google Workspace CLI - Gmail, Calendar, Drive, Sheets, Docs from your terminal"
  homepage "https://github.com/v-gutierrez/gw"
  url "https://github.com/v-gutierrez/gw/archive/refs/tags/v0.5.0.tar.gz"
  # sha256 will be filled after the v0.5.0 tag is pushed to GitHub
  # Run: curl -sL https://github.com/v-gutierrez/gw/archive/refs/tags/v0.5.0.tar.gz | shasum -a 256
  sha256 "FILL_AFTER_TAG_IS_CREATED"
  license "MIT"

  depends_on "python@3.11"

  resource "click" do
    url "https://files.pythonhosted.org/packages/source/c/click/click-8.1.8.tar.gz"
    sha256 "ed53c9d8821d0d21dea4c32f6be88d6b3abf8571628e98a7d32fa065d6e4b09a"
  end

  resource "google-auth" do
    url "https://files.pythonhosted.org/packages/source/g/google-auth/google_auth-2.38.0.tar.gz"
    sha256 "FILL_VIA_pip_download"
  end

  resource "google-auth-oauthlib" do
    url "https://files.pythonhosted.org/packages/source/g/google-auth-oauthlib/google_auth_oauthlib-1.2.1.tar.gz"
    sha256 "FILL_VIA_pip_download"
  end

  resource "google-api-python-client" do
    url "https://files.pythonhosted.org/packages/source/g/google-api-python-client/google_api_python_client-2.166.0.tar.gz"
    sha256 "FILL_VIA_pip_download"
  end

  resource "mcp" do
    url "https://files.pythonhosted.org/packages/source/m/mcp/mcp-1.26.0.tar.gz"
    sha256 "FILL_VIA_pip_download"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "0.5.0", shell_output("#{bin}/gw --version")
  end
end
