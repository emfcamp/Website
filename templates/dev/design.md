title: "Markdown styling"
show_nav: false
---

# h1 Heading
## h2 Heading
### h3 Heading
#### h4 Heading
##### h5 Heading
###### h6 Heading


## Horizontal Rules

Some text
***
Some more text


## Emphasis

**This is bold text**

*This is italic text*

***Bold italic text***

## HTML

Drop down to HTML for <s>strikethrough</s> or <u style="text-decoration-style: dashed">fancier styling</u>.

<style>
.customstyle { background-color: pink; color: #300; text-shadow: 0px 0px 4px #800 }
</style>
<div class="customstyle">You can even create custom CSS styles.</div>

There are no restrictions on HTML beyond the CSP, so you could iframe youtube if needed.

## Blockquotes


> Blockquotes can also be nested...
>> ...by using additional greater-than signs right next to each other...
> > > ...or with spaces between arrows.


## Lists

Unordered

- This is an unordered list
  - With subitems
    - and sub-sub-items

Ordered

1. Ordered list
   1. Subitem
      1. Subitem
   2. And a second
2. And a second here too


## Code

Inline `code`

Indented code

    // Some comments
    line 1 of code
    line 2 of code
    line 3 of code


Block code "fences"

```
Sample text here...
```

## Tables

Drop down to HTML again

<table><thead>
  <tr>
    <th>Heading</th>
    <th>Other</th>
  </tr>
</thead><tbody>
  <tr>
    <td>Cell</td>
    <td>Something else</td>
  </tr>
</tbody></table>

## Links

[link text](http://www.emfcamp.org/)

[link with title](http://www.emfcamp.org/about "About")

## Images

![Transparent logo](/static/images/logo-black-text.svg)
![Opaque](/static/images/logo-white-cropped.png "Logo on white background")

## Extensions

<style>
.admonition { background-color: red; box-shadow: 2px 2px 4px #c00; margin-top: 10px; }
.toc { background-color: #222 }
</style>

!!! info "This is an admonition"

And a table of contents:

[TOC]

