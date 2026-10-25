cmake_minimum_required(VERSION 3.25)

project(mcp-drogon LANGUAGES CXX)

find_package(Drogon REQUIRED)

add_executable(mcp mcp.cc)
target_link_libraries(mcp PRIVATE Drogon::Drogon)
