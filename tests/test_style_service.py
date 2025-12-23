"""
Tests for the Style Service (Personalización Visual).

Run with: pytest tests/test_style_service.py -v
"""

import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


class TestStyleServiceHelpers:
    """Test helper functions in style_service."""
    
    def test_style_key_files_mapping(self):
        """Verify STYLE_KEY_FILES contains expected mappings."""
        from app.services.style_service import STYLE_KEY_FILES
        
        assert "style_css" in STYLE_KEY_FILES
        assert "logo_header" in STYLE_KEY_FILES
        assert "logo_hero" in STYLE_KEY_FILES
        assert "placeholder" in STYLE_KEY_FILES
        
        # Check CSS filename
        assert STYLE_KEY_FILES["style_css"] == "style.css"

    def test_get_cache_dir_creates_directory(self, tmp_path):
        """Test that cache directory is created if it doesn't exist."""
        from app.services.style_service import get_cache_dir
        
        with patch('app.services.style_service.CACHE_DIR', str(tmp_path / "cache" / "styles")):
            cache_dir = get_cache_dir("TestStyle")
            assert os.path.exists(cache_dir)
            assert "TestStyle" in cache_dir


class TestGetActiveStyleName:
    """Tests for get_active_style_name function."""
    
    def test_returns_default_when_no_setting(self, app_context):
        """Should return default style when no setting exists."""
        from app.services.style_service import get_active_style_name, DEFAULT_STYLE
        
        with patch('app.services.style_service.SiteSetting') as mock_setting:
            mock_setting.get.return_value = None
            
            result = get_active_style_name()
            assert result == DEFAULT_STYLE
    
    def test_returns_configured_style(self, app_context):
        """Should return the configured active style."""
        from app.services.style_service import get_active_style_name
        
        with patch('app.services.style_service.SiteSetting') as mock_setting:
            mock_setting.get.return_value = "CustomStyle"
            
            result = get_active_style_name()
            assert result == "CustomStyle"


class TestSetActiveStyle:
    """Tests for set_active_style function."""
    
    def test_sets_active_style(self, app_context):
        """Should set the active style in database."""
        from app.services.style_service import set_active_style
        
        with patch('app.services.style_service.SiteSetting') as mock_setting:
            result = set_active_style("NewStyle")
            
            mock_setting.set.assert_called_once()
            assert result is True
    
    def test_returns_false_on_error(self, app_context):
        """Should return False when setting fails."""
        from app.services.style_service import set_active_style
        
        with patch('app.services.style_service.SiteSetting') as mock_setting:
            mock_setting.set.side_effect = Exception("DB Error")
            
            result = set_active_style("NewStyle")
            assert result is False


class TestListStyles:
    """Tests for list_styles function."""
    
    def test_returns_empty_list_when_no_drive(self, app_context):
        """Should return empty list when Drive is not configured."""
        from app.services.style_service import list_styles
        
        with patch('app.services.style_service._get_styles_folder_id', return_value=None):
            result = list_styles()
            assert result == []
    
    def test_returns_styles_from_drive(self, app_context):
        """Should return list of styles from Drive."""
        from app.services.style_service import list_styles
        
        mock_files = [
            {"id": "folder1", "name": "Navidad", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "folder2", "name": "General", "mimeType": "application/vnd.google-apps.folder"},
        ]
        
        with patch('app.services.style_service._get_styles_folder_id', return_value="root123"):
            with patch('app.services.style_service.list_folder_contents', return_value=mock_files):
                result = list_styles()
                
                assert len(result) == 2
                assert any(s["name"] == "Navidad" for s in result)
                assert any(s["name"] == "General" for s in result)


class TestGetStyleFileUrl:
    """Tests for style URL resolution."""
    
    def test_fallback_to_local_css(self, app_context):
        """Should fallback to local CSS when Drive fails."""
        from app.services.style_service import get_style_file_url
        
        with patch('app.services.style_service._get_drive_file_for_style', return_value=None):
            with patch('flask.url_for', return_value="/static/css/AMPA.css"):
                url = get_style_file_url("NonExistent", "style.css")
                
                # Should return the local fallback
                assert url is not None
    
    def test_returns_drive_url_when_available(self, app_context):
        """Should return Drive URL when file exists."""
        from app.services.style_service import get_style_file_url
        
        mock_file = {"id": "file123", "name": "style.css"}
        
        with patch('app.services.style_service._get_drive_file_for_style', return_value=mock_file):
            with patch('flask.url_for', return_value="/style/Navidad/style.css"):
                url = get_style_file_url("Navidad", "style.css")
                
                assert url is not None


class TestGetActiveStyleWithFallback:
    """Tests for get_active_style_with_fallback function."""
    
    def test_returns_complete_style_dict(self, app_context):
        """Should return dict with all required keys."""
        from app.services.style_service import get_active_style_with_fallback
        
        with patch('app.services.style_service.get_active_style_name', return_value="Navidad"):
            with patch('app.services.style_service.get_style_file_url') as mock_url:
                mock_url.return_value = "/style/test"
                
                result = get_active_style_with_fallback()
                
                assert "style_css" in result
                assert "logo_header" in result
                assert "logo_hero" in result
                assert "placeholder" in result
                assert "active_style" in result
    
    def test_uses_fallback_urls_on_error(self, app_context):
        """Should use local fallback URLs when Drive fails."""
        from app.services.style_service import get_active_style_with_fallback
        
        with patch('app.services.style_service.get_active_style_name', side_effect=Exception("Error")):
            with patch('flask.url_for') as mock_url:
                mock_url.return_value = "/static/fallback"
                
                result = get_active_style_with_fallback()
                
                # Should still return a valid dict with fallbacks
                assert isinstance(result, dict)
                assert "style_css" in result


class TestCacheInvalidation:
    """Tests for cache invalidation."""
    
    def test_invalidate_specific_style(self, tmp_path):
        """Should invalidate cache for specific style."""
        from app.services.style_service import invalidate_style_cache
        
        # Create mock cache directory
        style_cache = tmp_path / "TestStyle"
        style_cache.mkdir()
        (style_cache / "style.css").write_text("/* cached */")
        (style_cache / "_metadata.json").write_text("{}")
        
        with patch('app.services.style_service.CACHE_DIR', str(tmp_path)):
            invalidate_style_cache("TestStyle")
            
            # Directory should be removed or empty
            assert not (style_cache / "style.css").exists()
    
    def test_invalidate_all_styles(self, tmp_path):
        """Should invalidate cache for all styles."""
        from app.services.style_service import invalidate_style_cache
        
        # Create mock cache directories
        for style in ["Style1", "Style2"]:
            style_cache = tmp_path / style
            style_cache.mkdir()
            (style_cache / "style.css").write_text("/* cached */")
        
        with patch('app.services.style_service.CACHE_DIR', str(tmp_path)):
            invalidate_style_cache()  # No style name = invalidate all
            
            # All style caches should be cleared
            for style in ["Style1", "Style2"]:
                assert not (tmp_path / style / "style.css").exists()


class TestDownloadStyleFile:
    """Tests for download_style_file function."""
    
    def test_returns_cached_file_when_valid(self, tmp_path, app_context):
        """Should return cached file if cache is valid."""
        from app.services.style_service import download_style_file
        
        # Create valid cache
        cache_dir = tmp_path / "TestStyle"
        cache_dir.mkdir()
        cached_file = cache_dir / "style.css"
        cached_file.write_text("/* cached css */")
        
        metadata = {
            "files": {
                "style.css": {
                    "cached_at": datetime.utcnow().isoformat(),
                    "drive_id": "file123"
                }
            }
        }
        (cache_dir / "_metadata.json").write_text(json.dumps(metadata))
        
        with patch('app.services.style_service.CACHE_DIR', str(tmp_path)):
            with patch('app.services.style_service.CACHE_TTL', 3600):
                content, mime_type = download_style_file("TestStyle", "style.css")
                
                # Should return cached content without hitting Drive
                assert b"cached css" in content
    
    def test_downloads_from_drive_when_cache_expired(self, tmp_path, app_context):
        """Should download from Drive when cache is expired."""
        from app.services.style_service import download_style_file
        
        # Create expired cache
        cache_dir = tmp_path / "TestStyle"
        cache_dir.mkdir()
        
        old_time = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        metadata = {
            "files": {
                "style.css": {
                    "cached_at": old_time,
                    "drive_id": "file123"
                }
            }
        }
        (cache_dir / "_metadata.json").write_text(json.dumps(metadata))
        
        with patch('app.services.style_service.CACHE_DIR', str(tmp_path)):
            with patch('app.services.style_service.CACHE_TTL', 3600):
                with patch('app.services.style_service._download_from_drive') as mock_download:
                    mock_download.return_value = (b"/* fresh css */", "text/css")
                    
                    content, mime_type = download_style_file("TestStyle", "style.css")
                    
                    # Should have called Drive download
                    mock_download.assert_called()


class TestInitializeDefaultStyles:
    """Tests for initialize_default_styles function."""
    
    def test_creates_default_styles(self, app_context):
        """Should create Navidad and General styles."""
        from app.services.style_service import initialize_default_styles
        
        with patch('app.services.style_service._get_styles_folder_id', return_value="root123"):
            with patch('app.services.style_service._style_exists', return_value=False):
                with patch('app.services.style_service._create_style_folder') as mock_create:
                    with patch('app.services.style_service._upload_default_assets'):
                        result = initialize_default_styles()
                        
                        assert result["ok"] is True
                        assert "Navidad" in result.get("styles_created", [])
    
    def test_skips_existing_styles(self, app_context):
        """Should skip styles that already exist."""
        from app.services.style_service import initialize_default_styles
        
        with patch('app.services.style_service._get_styles_folder_id', return_value="root123"):
            with patch('app.services.style_service._style_exists', return_value=True):
                result = initialize_default_styles(overwrite=False)
                
                assert "styles_skipped" in result


# Fixtures

@pytest.fixture
def app_context():
    """Create Flask app context for tests."""
    from flask import Flask
    
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    
    with app.app_context():
        yield app

@pytest.fixture
def tmp_path(tmp_path_factory):
    """Create temporary directory for cache tests."""
    return tmp_path_factory.mktemp("style_cache")


# Integration tests (require actual Drive connection)

class TestStyleServiceIntegration:
    """Integration tests that require Drive connection.
    
    These tests are skipped by default. Run with:
    pytest tests/test_style_service.py -v -m integration
    """
    
    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires actual Drive connection")
    def test_full_style_workflow(self, app_context):
        """Test complete workflow: create, list, activate, delete style."""
        from app.services.style_service import (
            create_style,
            list_styles,
            set_active_style,
            get_active_style_name,
            delete_style
        )
        
        test_style_name = f"TestStyle_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        try:
            # Create style
            result = create_style(test_style_name)
            assert result["ok"] is True
            
            # List styles
            styles = list_styles()
            assert any(s["name"] == test_style_name for s in styles)
            
            # Activate style
            assert set_active_style(test_style_name) is True
            assert get_active_style_name() == test_style_name
            
        finally:
            # Cleanup
            delete_style(test_style_name)
