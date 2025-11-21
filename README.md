# Latent portfolio

> 🌐 **Visit the live demo**: [http://laurenci.ch](http://laurenci.ch)

This project allows you to view a list of projects as a 3D representation of their semantic latent space.


![latent_portfolio preview](latent_portfolio/src/assets/latent_portfolio_prev.jpg)


## Usage

The easiest way to use this project is to **fork** the repository and configure Github pages.

1. **Enable GitHub Pages**: Go to your repository Settings → Pages
2. **Set source**: Select "GitHub Actions" as the publishing source
3. **Set deployment branch**: Go to Settings → Environments → Deployment branches → Edit pattern to `public`
4. **Push changes**: The workflow will automatically build and test your site when you push to the `public` branch

For detailed instructions, see the [GitHub Pages documentation on publishing with a custom GitHub Actions workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-with-a-custom-github-actions-workflow).

The site will be available at:
- `https://<your-username>.github.io/` if your repository is named `<your-username>.github.io`
- `https://<your-username>.github.io/<repository-name>/` otherwise

### Customizing your fork

To customize the configuration, copy `config.toml.template` to `config.toml` and modify it according to your needs.

You can customize your name and contact data, tweak the style, or adjust the fields used for dimensionality reduction. By creating your own `config.toml` file (instead of modifying the template), your customizations won't be overridden when pulling updates from the upstream repository. The build script will automatically detect and use your custom configuration file.

### Create your articles

Create an `articles` folder at the root of this repository, and populate it with markdown files, using [sample_articles/_article_boilerplate.md](sample_articles/_article_boilerplate.md) as a base.

**Be sure to populate the JSON part with significant content**, since it will be used to create the embeddings of your article. Add at least 2 technologies and 2 tags.

## Dev Run

To run the project locally to test the changes before pushing:

1. **Clone and Install dependencies:**
   ```bash
   git clone https://github.com/daylanKifky/latent_portfolio
   cd latent_portfolio
   pip install -e .
   ```

2. **Process articles and generate embeddings:**
   This step reads all markdown files from the `articles` folder, generates semantic embeddings, applies dimensionality reduction, and calculates cross-similarities between projects.
   ```bash
   python -m latent_portfolio.build -i articles
   ```

3. **Serve the visualization:**
   Start a local web server to view the 3D visualization in your browser.
   ```bash
   cd public
   python -m http.server 8080
   ```

   Then open `http://localhost:8080` in your browser to see the interactive 3D visualization.

## How it works

### Semantic Space

Each project article is converted into a high-dimensional semantic embedding using a sentence transformer model. This embedding captures the semantic meaning of the project's content (title, description, tags, etc.) as a vector in a semantic space where similar projects are positioned closer together.

### Dimensionality Reduction with PCA

The high-dimensional embeddings (typically 384 or 768 dimensions) are reduced to 3D coordinates using [Principal Component Analysis](https://en.wikipedia.org/wiki/Principal_component_analysis). PCA finds the principal components that capture the most variance in the data, allowing the semantic relationships to be visualized in 3D space while preserving as much information as possible.

While other dimensionality reduction methods such as [UMAP](https://umap-learn.readthedocs.io/en/latest/) and [t-SNE](https://en.wikipedia.org/wiki/T-distributed_stochastic_neighbor_embedding) are also available, PCA tends to produce well-defined clusters that work better for visualizing project relationships in this use case.


### Positioning Points in Space

The reduced 3D coordinates are used to position each project as a point in the 3D visualization. Projects with similar semantic content will be positioned closer together in this space, creating natural clusters of related projects.

Colors are also derived from the 3D coordinates, making articles within a cluster use similar colors.

### Cross Similarity for Links

Connecting arcs are drawn between projects based on their cross-similarity scores. The system calculates similarity between all pairs of projects across different fields (title, tags, etc.), and uses these scores to determine which projects should be visually connected. The thickness and opacity of the arcs represent the strength of the semantic relationship between projects.

## Advanced Customization

For advanced users who need more control over the HTML structure, you can insert custom HTML snippets that will be automatically included in the generated pages. 

See the `latent_portfolio/src/user_templates`, each file contains comments explaining its purpose and example use cases. Simply edit these files to add your custom HTML, scripts, analytics, or other content without modifying the core template files. This makes it easier to maintain your customizations when pulling updates from the upstream repository.


## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

**Important**: When using this project, please retain the credit text that appears in the generated pages (the "made with Latent Portfolio" attribution). This helps others discover and use this tool :)
