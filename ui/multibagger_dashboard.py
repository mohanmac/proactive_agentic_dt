"""
Multi-Bagger Stock Analysis Dashboard
Interactive Streamlit UI to explore high-growth stock patterns and prospects
"""
import streamlit as st
import pandas as pd
import json
from pathlib import Path
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# Page config
st.set_page_config(
    page_title="Multi-Bagger Analysis Dashboard",
    page_icon="https://raw.githubusercontent.com/mohanmac/proactive_agentic_dt/main/favicon_512.png",
    layout="wide"
)

# Load analysis data
@st.cache_data
def load_analysis_data():
    """Load the analysis results."""
    data_file = Path(__file__).parent.parent / "data" / "multibagger_analysis_report.json"
    
    if not data_file.exists():
        return None
    
    with open(data_file, 'r') as f:
        data = json.load(f)
    
    return data

# Main app
def main():
    st.title("🚀 Multi-Bagger Stock Analysis Dashboard")
    st.markdown("---")
    
    # Load data
    data = load_analysis_data()
    
    if data is None:
        st.error("❌ Analysis data not found. Please run the analysis first:")
        st.code("python scripts/multibagger_analysis.py")
        return
    
    # Sidebar filters
    st.sidebar.header("🔍 Filters")
    
    min_score = st.sidebar.slider(
        "Minimum Score",
        min_value=0,
        max_value=100,
        value=70,
        step=5
    )
    
    # Get unique sectors from prospects
    all_sectors = set()
    for prospect in data.get('prospects', []):
        all_sectors.add(prospect['sector'])
    
    selected_sectors = st.sidebar.multiselect(
        "Sectors",
        options=sorted(all_sectors),
        default=sorted(all_sectors)
    )
    
    # Overview metrics
    st.header("📊 Analysis Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    
    # Get analysis date
    analysis_date = data.get('analysis_date', 'N/A')
    if 'T' in str(analysis_date):
        analysis_date = analysis_date.split('T')[0]
    
    with col1:
        st.metric(
            "📅 Analysis Date",
            analysis_date,
            f"{data['parameters']['lookback_years']} year lookback"
        )
    
    with col2:
        winners = data.get('historical_winners', [])
        st.metric(
            "✅ Multi-Baggers Found",
            len(winners),
            f"{sum(w['return_pct'] for w in winners)/len(winners):.1f}% avg" if winners else "N/A"
        )
    
    with col3:
        prospects = data.get('prospects', [])
        # Handle both 'score' and 'total_score' keys
        high_score_count = 0
        for p in prospects:
            score = p.get('total_score', p.get('score', 0))
            if score >= 80:
                high_score_count += 1
        
        st.metric(
            "🎯 Top Prospects",
            high_score_count,
            "Score ≥ 80"
        )
    
    with col4:
        if winners:
            best = max(winners, key=lambda x: x['return_pct'])
            st.metric(
                "🏆 Best Performer",
                best['symbol'],
                f"+{best['return_pct']:.1f}%"
            )
    
    st.markdown("---")
    
    # Winners Section
    st.header("🏆 Multi-Bagger Winners (200%+ Returns)")
    
    winners = data.get('historical_winners', [])
    if not winners:
        st.warning("No winners data available")
        return
    
    winners_df = pd.DataFrame(winners)
    winners_df = winners_df.sort_values('return_pct', ascending=False)
    
    # Bar chart of returns
    fig_returns = px.bar(
        winners_df,
        x='symbol',
        y='return_pct',
        color='sector',
        title='Multi-Bagger Returns by Stock',
        labels={'return_pct': 'Return (%)', 'symbol': 'Stock'},
        text='return_pct'
    )
    fig_returns.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
    fig_returns.update_layout(height=400)
    st.plotly_chart(fig_returns, use_container_width=True)
    
    # Winners table
    with st.expander("📋 View Winners Details"):
        display_cols = ['symbol', 'return_pct', 'sector', 'market_cap_cr', 
                        'revenue_growth', 'roe']
        format_dict = {
            'return_pct': '{:.1f}%',
            'market_cap_cr': '₹{:,.0f} Cr',
            'revenue_growth': '{:.1f}%',
            'roe': '{:.1f}%'
        }
        if 'pe_ratio' in winners_df.columns:
            display_cols.append('pe_ratio')
            format_dict['pe_ratio'] = '{:.1f}'
            
        st.dataframe(
            winners_df[display_cols].style.format(format_dict),
            use_container_width=True
        )
    
    st.markdown("---")
    
    # Pattern Analysis
    st.header("🔬 Winning Pattern Characteristics")
    
    pattern = data.get('winning_patterns', {})
    
    if pattern:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.subheader("💰 Market Cap Distribution")
            if 'market_cap' in pattern:
                st.metric("Median Market Cap", f"₹{pattern['market_cap'].get('median', 0):,.0f} Cr")
                st.metric("Range", f"₹{pattern['market_cap'].get('min', 0):,.0f} - {pattern['market_cap'].get('max', 0):,.0f} Cr")
        
        with col2:
            st.subheader("📈 Revenue Growth")
            if 'revenue_growth' in pattern:
                st.metric("Average Growth", f"{pattern['revenue_growth'].get('avg', 0):.1f}% YoY")
                st.metric("Median Growth", f"{pattern['revenue_growth'].get('median', 0):.1f}% YoY")
        
        with col3:
            st.subheader("💎 Return on Equity")
            if 'roe' in pattern:
                st.metric("Average ROE", f"{pattern['roe'].get('avg', 0):.1f}%")
                st.metric("Median ROE", f"{pattern['roe'].get('median', 0):.1f}%")
        
        # Sector distribution
        st.subheader("🏭 Sector Performance")
        if 'top_sectors' in pattern:
            sector_counts = pd.DataFrame(
                [(k, v) for k, v in pattern['top_sectors'].items()],
                columns=['Sector', 'Winners']
            )
            
            fig_sectors = px.pie(
                sector_counts,
                values='Winners',
                names='Sector',
                title='Multi-Baggers by Sector',
                hole=0.4
            )
            st.plotly_chart(fig_sectors, use_container_width=True)
    else:
        # Calculate patterns from winners data
        st.info("Calculating patterns from historical winners...")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.subheader("💰 Market Cap Distribution")
            st.metric("Median Market Cap", f"₹{winners_df['market_cap_cr'].median():,.0f} Cr")
            st.metric("Range", f"₹{winners_df['market_cap_cr'].min():,.0f} - {winners_df['market_cap_cr'].max():,.0f} Cr")
        
        with col2:
            st.subheader("📈 Revenue Growth")
            st.metric("Average Growth", f"{winners_df['revenue_growth'].mean():.1f}% YoY")
            st.metric("Median Growth", f"{winners_df['revenue_growth'].median():.1f}% YoY")
        
        with col3:
            st.subheader("💎 Return on Equity")
            st.metric("Average ROE", f"{winners_df['roe'].mean():.1f}%")
            st.metric("Median ROE", f"{winners_df['roe'].median():.1f}%")
        
        # Sector distribution
        st.subheader("🏭 Sector Performance")
        sector_counts = winners_df['sector'].value_counts().reset_index()
        sector_counts.columns = ['Sector', 'Winners']
        
        fig_sectors = px.pie(
            sector_counts,
            values='Winners',
            names='Sector',
            title='Multi-Baggers by Sector',
            hole=0.4
        )
        st.plotly_chart(fig_sectors, use_container_width=True)
    
    st.markdown("---")
    
    # Prospects Section
    st.header("🎯 High-Potential Prospect Stocks")
    
    # Load prospects
    prospects_raw = data.get('prospects', [])
    if not prospects_raw:
        st.warning("No prospects data available")
        return
    
    # Normalize prospect data
    prospects_list = []
    for p in prospects_raw:
        # Normalize the score field
        score = p.get('total_score', p.get('score', 0))
        
        # Create normalized prospect dict
        prospect = {
            'symbol': p.get('symbol', 'N/A'),
            'score': score,
            'sector': p.get('sector', 'N/A'),
            'current_price': p.get('current_price', 0),
            'market_cap': p.get('market_cap_cr', p.get('market_cap', 0)),
            'revenue_growth': p.get('revenue_growth', None),
            'roe': p.get('roe', None),
            'pe_ratio': p.get('pe_ratio', None),
            'volume_change': p.get('volume_change', None),
            'reasons': p.get('reasons', []),
            'similar_to': p.get('similar_to', '')
        }
        prospects_list.append(prospect)
    
    prospects_df = pd.DataFrame(prospects_list)
    
    # Filter prospects
    prospects_df = prospects_df[
        (prospects_df['score'] >= min_score) &
        (prospects_df['sector'].isin(selected_sectors))
    ]
    prospects_df = prospects_df.sort_values('score', ascending=False)
    
    st.info(f"📊 Showing {len(prospects_df)} prospects matching your filters")
    
    # Top 10 prospects
    st.subheader("🥇 Top 10 Prospects")
    
    top_10 = prospects_df.head(10)
    
    # Score chart
    fig_scores = go.Figure()
    fig_scores.add_trace(go.Bar(
        x=top_10['score'],
        y=top_10['symbol'],
        orientation='h',
        marker=dict(
            color=top_10['score'],
            colorscale='RdYlGn',
            showscale=True,
            colorbar=dict(title="Score")
        ),
        text=top_10['score'].apply(lambda x: f"{x:.0f}"),
        textposition='outside'
    ))
    
    fig_scores.update_layout(
        title='Top 10 Prospect Scores',
        xaxis_title='Score',
        yaxis_title='Stock',
        height=500,
        yaxis={'categoryorder': 'total ascending'}
    )
    
    st.plotly_chart(fig_scores, use_container_width=True)
    
    # Detailed prospect cards
    st.subheader("📊 Detailed Prospect Analysis")
    
    for idx, prospect in top_10.iterrows():
        with st.expander(f"**{prospect['symbol']}** - Score: {prospect['score']:.0f}/100"):
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("💰 Current Price", f"₹{prospect['current_price']:.2f}")
                st.metric("📊 Market Cap", f"₹{prospect['market_cap']:,.0f} Cr")
            
            with col2:
                st.metric("📈 Revenue Growth", f"{prospect.get('revenue_growth', 'N/A')}% YoY" if pd.notna(prospect.get('revenue_growth')) else "N/A")
                st.metric("💎 ROE", f"{prospect.get('roe', 'N/A')}%" if pd.notna(prospect.get('roe')) else "N/A")
            
            with col3:
                st.metric("📉 PE Ratio", f"{prospect.get('pe_ratio', 'N/A')}" if pd.notna(prospect.get('pe_ratio')) else "N/A")
                st.metric("📊 Volume Change", f"{prospect.get('volume_change', 'N/A')}%" if pd.notna(prospect.get('volume_change')) else "N/A")
            
            with col4:
                st.metric("🏭 Sector", prospect['sector'])
                
            # Reasons
            st.markdown("**✅ Key Reasons:**")
            for reason in prospect.get('reasons', []):
                st.markdown(f"- {reason}")
            
            # Similar winners
            if prospect.get('similar_to'):
                st.markdown(f"**🎯 Similar to:** {prospect['similar_to']}")
    
    st.markdown("---")
    
    # All prospects table
    st.subheader("📋 All Prospects (Filtered)")
    
    display_cols = ['symbol', 'score', 'sector', 'current_price', 'market_cap']
    
    # Add optional columns if they contain data
    optional_cols = ['revenue_growth', 'roe', 'pe_ratio', 'volume_change']
    for col in optional_cols:
        if col in prospects_df.columns and prospects_df[col].notna().any():
            display_cols.append(col)
    
    # Format config - only for columns that exist and have data
    format_dict = {
        'score': '{:.0f}',
        'current_price': '₹{:.2f}',
        'market_cap': '₹{:,.0f} Cr'
    }
    
    # Add formatting for optional columns
    if 'revenue_growth' in display_cols:
        format_dict['revenue_growth'] = '{:.1f}%'
    if 'roe' in display_cols:
        format_dict['roe'] = '{:.1f}%'
    if 'pe_ratio' in display_cols:
        format_dict['pe_ratio'] = '{:.1f}'
    if 'volume_change' in display_cols:
        format_dict['volume_change'] = '{:.1f}%'
    
    # Create a copy and fill None values with appropriate defaults
    display_df = prospects_df[display_cols].copy()
    display_df = display_df.fillna({
        'revenue_growth': 0.0,
        'roe': 0.0,
        'pe_ratio': 0.0,
        'volume_change': 0.0
    })
    
    st.dataframe(
        display_df.style.format(format_dict),
        use_container_width=True,
        height=400
    )
    
    st.markdown("---")
    
    # Scatter analysis
    st.header("📈 Correlation Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Revenue Growth vs Score
        if 'revenue_growth' in prospects_df.columns:
            fig_rev = px.scatter(
                prospects_df,
                x='revenue_growth',
                y='score',
                color='sector',
                size='market_cap',
                hover_data=['symbol'],
                title='Revenue Growth vs Prospect Score',
                labels={'revenue_growth': 'Revenue Growth (%)', 'score': 'Score'}
            )
            st.plotly_chart(fig_rev, use_container_width=True)
    
    with col2:
        # ROE vs Score
        if 'roe' in prospects_df.columns:
            fig_roe = px.scatter(
                prospects_df,
                x='roe',
                y='score',
                color='sector',
                size='market_cap',
                hover_data=['symbol'],
                title='ROE vs Prospect Score',
                labels={'roe': 'ROE (%)', 'score': 'Score'}
            )
            st.plotly_chart(fig_roe, use_container_width=True)
    
    st.markdown("---")
    
    # Export section
    st.header("💾 Export Data")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Export top prospects
        if st.button("📥 Export Top 20 Prospects to CSV"):
            export_df = prospects_df.head(20)
            csv = export_df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"top_prospects_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
    
    with col2:
        # Export full JSON
        if st.button("📥 Export Full Analysis JSON"):
            json_str = json.dumps(data, indent=2)
            st.download_button(
                label="Download JSON",
                data=json_str,
                file_name=f"multibagger_analysis_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json"
            )
    
    # Footer
    st.markdown("---")
    st.caption(f"Analysis generated on: {analysis_date}")
    st.caption("⚠️ This analysis is for educational purposes only. Not investment advice. Past performance doesn't guarantee future results.")

if __name__ == "__main__":
    main()
