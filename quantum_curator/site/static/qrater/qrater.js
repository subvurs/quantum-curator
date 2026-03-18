(function () {
  'use strict';

  // --- State ---
  var allArticles = [];
  var filteredArticles = [];
  var activeTopics = new Set();
  var activeSources = new Set();
  var dateRange = { from: null, to: null, preset: 'all' };
  var sortBy = 'date-desc';

  // --- DOM refs ---
  var grid = document.getElementById('articles-grid');
  var countEl = document.getElementById('results-count');
  var filterPanel = document.getElementById('filters-panel');

  // --- Utilities ---
  function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str || ''));
    return div.innerHTML;
  }

  function truncate(str, len) {
    if (!str) return '';
    return str.length > len ? str.substring(0, len) + '...' : str;
  }

  // --- Data Loading ---
  function loadArticles() {
    fetch('./data/articles.json')
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        allArticles = data;
        initTopics();
        applyFilters();
      })
      .catch(function (err) {
        grid.innerHTML = '<p class="no-results">Failed to load articles. Please try refreshing.</p>';
        console.error('Failed to load articles:', err);
      });
  }

  // --- Init topics from checkboxes ---
  function initTopics() {
    document.querySelectorAll('.topic-checkbox').forEach(function (cb) {
      if (cb.checked) activeTopics.add(cb.value);
    });
  }

  // --- Filtering ---
  function applyFilters() {
    filteredArticles = allArticles.filter(function (article) {
      // Topic filter
      if (activeTopics.size > 0) {
        var hasMatchingTopic = article.topics.some(function (t) {
          return activeTopics.has(t);
        });
        if (!hasMatchingTopic) return false;
      }

      // Source filter
      if (activeSources.size > 0 && !activeSources.has(article.source)) {
        return false;
      }

      // Date range filter
      if (article.date_iso && (dateRange.from || dateRange.to)) {
        var d = new Date(article.date_iso);
        if (dateRange.from && d < dateRange.from) return false;
        if (dateRange.to) {
          var endOfDay = new Date(dateRange.to);
          endOfDay.setHours(23, 59, 59, 999);
          if (d > endOfDay) return false;
        }
      }

      return true;
    });

    sortArticles();
    renderGrid();
    updateCount();
  }

  function sortArticles() {
    filteredArticles.sort(function (a, b) {
      switch (sortBy) {
        case 'date-desc':
          return new Date(b.date_iso || 0) - new Date(a.date_iso || 0);
        case 'date-asc':
          return new Date(a.date_iso || 0) - new Date(b.date_iso || 0);
        case 'relevance':
          return (b.relevance_score || 0) - (a.relevance_score || 0);
        default:
          return 0;
      }
    });
  }

  // --- Date Presets ---
  function setDatePreset(preset) {
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    // Clear custom date inputs
    var fromInput = document.getElementById('date-from');
    var toInput = document.getElementById('date-to');
    if (fromInput) fromInput.value = '';
    if (toInput) toInput.value = '';

    switch (preset) {
      case 'today':
        dateRange = { from: today, to: null, preset: 'today' };
        break;
      case 'week':
        var weekAgo = new Date(today);
        weekAgo.setDate(weekAgo.getDate() - 7);
        dateRange = { from: weekAgo, to: null, preset: 'week' };
        break;
      case 'month':
        var monthAgo = new Date(today);
        monthAgo.setMonth(monthAgo.getMonth() - 1);
        dateRange = { from: monthAgo, to: null, preset: 'month' };
        break;
      case 'all':
      default:
        dateRange = { from: null, to: null, preset: 'all' };
        break;
    }

    // Update active button
    document.querySelectorAll('.preset-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.range === preset);
    });

    applyFilters();
  }

  function handleCustomDate() {
    var fromInput = document.getElementById('date-from');
    var toInput = document.getElementById('date-to');

    dateRange.from = fromInput.value ? new Date(fromInput.value) : null;
    dateRange.to = toInput.value ? new Date(toInput.value) : null;
    dateRange.preset = 'custom';

    // Clear preset active state
    document.querySelectorAll('.preset-btn').forEach(function (btn) {
      btn.classList.remove('active');
    });

    applyFilters();
  }

  // --- Rendering ---
  function renderGrid() {
    if (filteredArticles.length === 0) {
      grid.innerHTML = '<p class="no-results">No articles match your filters. Try broadening your selection.</p>';
      return;
    }

    grid.innerHTML = filteredArticles.map(function (article) {
      var topicTags = article.topics.map(function (t) {
        return '<span class="topic-tag t-' + escapeHtml(t) + '">' +
          escapeHtml(t.replace(/_/g, ' ')) + '</span>';
      }).join('');

      var imageHtml = article.image_url
        ? '<div class="card-image"><img src="' + escapeHtml(article.image_url) +
          '" alt="" loading="lazy" onerror="this.parentElement.style.display=\'none\'"></div>'
        : '';

      var commentaryHtml = article.commentary
        ? '<div class="card-commentary">' + escapeHtml(truncate(article.commentary, 150)) + '</div>'
        : '';

      var relevancePercent = Math.round((article.relevance_score || 0) * 100);

      return '<article class="qrater-card">' +
        imageHtml +
        '<div class="card-body">' +
          '<div class="card-topics">' + topicTags + '</div>' +
          '<h3 class="card-title"><a href="' + escapeHtml(article.original_url) +
            '" target="_blank" rel="noopener">' + escapeHtml(article.title) + '</a></h3>' +
          '<p class="card-summary">' + escapeHtml(truncate(article.summary, 200)) + '</p>' +
          commentaryHtml +
          '<div class="card-meta">' +
            '<span class="card-source">' + escapeHtml(article.source) + '</span>' +
            '<span class="card-date">' + escapeHtml(article.date) + '</span>' +
            '<span class="relevance-badge" title="Relevance: ' + relevancePercent + '%">' +
              relevancePercent + '%</span>' +
          '</div>' +
        '</div>' +
      '</article>';
    }).join('');
  }

  function updateCount() {
    countEl.textContent = 'Showing ' + filteredArticles.length + ' of ' + allArticles.length + ' articles';
  }

  // --- Event Binding ---
  function bindEvents() {
    // Topic checkboxes
    document.querySelectorAll('.topic-checkbox').forEach(function (cb) {
      cb.addEventListener('change', function () {
        if (cb.checked) activeTopics.add(cb.value);
        else activeTopics.delete(cb.value);
        applyFilters();
      });
    });

    // Select All / Clear All
    var selectAll = document.getElementById('select-all');
    var clearAll = document.getElementById('clear-all');

    if (selectAll) {
      selectAll.addEventListener('click', function () {
        document.querySelectorAll('.topic-checkbox').forEach(function (cb) {
          cb.checked = true;
          activeTopics.add(cb.value);
        });
        applyFilters();
      });
    }

    if (clearAll) {
      clearAll.addEventListener('click', function () {
        document.querySelectorAll('.topic-checkbox').forEach(function (cb) {
          cb.checked = false;
        });
        activeTopics.clear();
        applyFilters();
      });
    }

    // Date presets
    document.querySelectorAll('.preset-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setDatePreset(btn.dataset.range);
      });
    });

    // Custom dates
    var dateFrom = document.getElementById('date-from');
    var dateTo = document.getElementById('date-to');
    if (dateFrom) dateFrom.addEventListener('change', handleCustomDate);
    if (dateTo) dateTo.addEventListener('change', handleCustomDate);

    // Source filter
    var sourceFilter = document.getElementById('source-filter');
    if (sourceFilter) {
      sourceFilter.addEventListener('change', function () {
        activeSources.clear();
        if (sourceFilter.value) {
          activeSources.add(sourceFilter.value);
        }
        applyFilters();
      });
    }

    // Sort
    var sortSelect = document.getElementById('sort-by');
    if (sortSelect) {
      sortSelect.addEventListener('change', function () {
        sortBy = sortSelect.value;
        applyFilters();
      });
    }

    // Mobile filter toggle
    var filterToggle = document.getElementById('filter-toggle');
    if (filterToggle && filterPanel) {
      filterToggle.addEventListener('click', function () {
        filterPanel.classList.toggle('open');
      });

      // Close panel when clicking on main content (mobile)
      document.querySelector('.main-content').addEventListener('click', function () {
        filterPanel.classList.remove('open');
      });
    }
  }

  // --- Init ---
  document.addEventListener('DOMContentLoaded', function () {
    bindEvents();
    loadArticles();
  });
})();
